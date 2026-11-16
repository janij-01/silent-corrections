"""Run the repo's judge on one results file, saving each row as soon as it is judged.

Same prompt, model, temperature and row format as `python -m stale_facts.judge`. Differences:
- every judged row is appended to judged.partial.jsonl at once, so a stop loses nothing;
- a rerun skips rows already in that file (rows that failed on a request error are retried);
- progress is printed every 10 rows;
- the wait after a rate-limit reply is capped at CAP seconds.
When all rows are done it writes judged.jsonl in the original order.

    python run_judge_incremental.py <repo> <results.jsonl> [--workers 3]
"""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CAP = 15.0
repo, path = sys.argv[1], Path(sys.argv[2])
workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 3
sys.path.insert(0, repo)

from stale_facts import judge, run_pilot  # noqa: E402

_server_wait = run_pilot.retry_wait_seconds
run_pilot.retry_wait_seconds = lambda exc, body: min(CAP, _server_wait(exc, body))


LIMIT = int(sys.argv[sys.argv.index("--max-output-tokens") + 1]) if "--max-output-tokens" in sys.argv else 8192


def settled(row: dict) -> bool:
    """Settled = judged, skipped on purpose, or unparsed. A judge reply that ran out of output
    tokens while still reasoning is retried if the limit is now higher than it was then."""
    error = row.get("judge_error")
    if error is None or error.startswith("not judged"):
        return True
    if error == "unparsed judge reply":
        cut_off = row.get("judge_status") == "incomplete"
        return not (cut_off and row.get("judge_max_output_tokens", 4096) < LIMIT)
    return False


def judge_row(row: dict, client) -> dict:
    judged = judge.judge_one(row, client)
    judged["judge_max_output_tokens"] = LIMIT
    return judged


rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
partial = path.with_name("judged.partial.jsonl")
done: dict[str, dict] = {}
earlier = path.with_name("judged.jsonl")  # a finished earlier pass counts as progress too
for source in (earlier, partial):
    if source.exists():
        for line in source.open(encoding="utf-8"):
            if line.strip():
                row = json.loads(line)
                if settled(row):
                    done[row["id"]] = row
todo = [row for row in rows if row["id"] not in done]
name = path.parent.name
if "--finalize" in sys.argv:
    # Stop retrying: write judged.jsonl now, keeping the recorded request error on rows that never got through.
    latest = {}
    for source in (earlier, partial):
        if source.exists():
            for line in source.open(encoding="utf-8"):
                if line.strip():
                    row = json.loads(line)
                    latest[row["id"]] = row
    final = [done.get(row["id"]) or latest[row["id"]] for row in rows]
    with path.with_name("judged.jsonl").open("w", encoding="utf-8") as handle:
        for row in final:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{name}] finalized: {sum(r.get('judge_type') is not None for r in final)}/{len(final)} judged, "
          f"{sum(not settled(r) for r in final)} left with a request error or cut-off", flush=True)
    sys.exit(0)
print(f"[{name}] {len(rows)} rows, {len(done)} already judged, {len(todo)} to do, {workers} workers", flush=True)

client = run_pilot.make_client("adaption", judge.JUDGE_MODEL, temperature=0, max_output_tokens=LIMIT)
lock = threading.Lock()
start = time.time()
count = problems = 0
with partial.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max(1, workers)) as pool:
    for future in as_completed([pool.submit(judge_row, row, client) for row in todo]):
        row = future.result()
        with lock:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            done[row["id"]] = row
            count += 1
            problems += bool(row.get("judge_error"))
            if count % 10 == 0 or count == len(todo):
                print(f"[{name}] {count}/{len(todo)} in {time.time() - start:.0f}s, "
                      f"{problems} not judged or unparsed", flush=True)

if all(settled(done[row["id"]]) for row in rows):
    with path.with_name("judged.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(done[row["id"]], ensure_ascii=False) + "\n")
    print(f"[{name}] wrote judged.jsonl", flush=True)
else:
    left = sum(not settled(done[row["id"]]) for row in rows)
    print(f"[{name}] {left} rows failed on request errors; run again to retry them", flush=True)
