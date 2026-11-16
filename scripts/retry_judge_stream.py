"""Re-judge the rows whose judge request timed out at the gateway, using a streaming request.

Same judge model, prompt, temperature and output limit as the other rows; only the transport
differs (stream=true, so the connection stays active while the judge reasons). A row that
comes back is appended to judged.partial.jsonl with judge_transport = "stream".

    python retry_judge_stream.py <repo> <results.jsonl> [--limit N] [--max-output-tokens 8192]
"""

import collections
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

repo, path = sys.argv[1], Path(sys.argv[2])
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
LIMIT = int(sys.argv[sys.argv.index("--max-output-tokens") + 1]) if "--max-output-tokens" in sys.argv else 8192
sys.path.insert(0, repo)

from stale_facts import judge, run_pilot  # noqa: E402


def stream_call(system: str, user: str) -> dict:
    payload = {
        "model": judge.JUDGE_MODEL,
        "instructions": system,
        "input": run_pilot.messages_to_adaption_input([{"role": "user", "content": user}]),
        "temperature": 0,
        "max_output_tokens": LIMIT,
        "agentic_memory": False,
        "store": False,
        "stream": True,
    }
    request = urllib.request.Request(
        run_pilot.ADAPTION_URL, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {os.environ['ADAPTION_API_KEY']}",
                 "Content-Type": "application/json", "Accept": "text/event-stream"})
    events = collections.Counter()
    deltas, final = [], None
    with urllib.request.urlopen(request, timeout=300) as response:
        content_type = response.headers.get("Content-Type", "")
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                events["(unparsed line)"] += 1
                continue
            kind = event.get("type") or "(no type)"
            events[kind] += 1
            if kind.endswith("output_text.delta") and isinstance(event.get("delta"), str):
                deltas.append(event["delta"])
            if isinstance(event.get("response"), dict) and event["response"].get("status") in (
                    "completed", "incomplete", "failed"):
                final = event["response"]
            elif event.get("object") == "response" and event.get("status") in ("completed", "incomplete", "failed"):
                final = event
    text = ""
    if final:
        parts = [part.get("text", "") for item in final.get("output") or [] if item.get("type") == "message"
                 for part in item.get("content") or [] if part.get("type") == "output_text"]
        text = "\n".join(p for p in parts if p).strip() or (final.get("output_text") or "")
    text = text or "".join(deltas).strip()
    usage = (final or {}).get("usage") or {}
    return {"text": text, "status": (final or {}).get("status"), "content_type": content_type,
            "events": dict(events),
            "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                      "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                      "cost": usage.get("cost")}}


judged = [json.loads(line) for line in path.with_name("judged.jsonl").open(encoding="utf-8") if line.strip()]
todo = [row for row in judged if (row.get("judge_error") or "").startswith("HTTP 504")]
name = path.parent.name
print(f"[{name}] {len(todo)} rows timed out earlier", flush=True)
for row in todo[:limit]:
    start = time.time()
    try:
        got = stream_call(judge.RUBRIC, judge.judge_case(row))
    except urllib.error.HTTPError as exc:
        print(f"[{name}] {row['id']}: HTTP {exc.code} after {time.time() - start:.0f}s "
              f"{exc.read().decode(errors='replace')[:200]!r}", flush=True)
        continue
    except Exception as exc:  # report and move on
        print(f"[{name}] {row['id']}: {type(exc).__name__} after {time.time() - start:.0f}s: {exc}", flush=True)
        continue
    kind, value, reason = judge.parse_judge(got["text"])
    print(f"[{name}] {row['id']}: {time.time() - start:.0f}s status={got['status']} type={kind} value={value} "
          f"usage={got['usage']} content_type={got['content_type']} events={got['events']}", flush=True)
    if kind is None or value is None:
        continue
    row = dict(row)
    row.update({"judge_type": kind, "judge_value_used": value, "judge_reason": reason, "judge_raw": got["text"],
                "judge_status": got["status"], "judge_usage": got["usage"], "judge_error": None,
                "judge_max_output_tokens": LIMIT, "judge_transport": "stream"})
    with path.with_name("judged.partial.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
