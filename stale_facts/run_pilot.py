"""Pilot runner. Stdlib only, so a model call does not need the Inspect install.

Examples:
  python -m stale_facts.run_pilot --dry-run
  python -m stale_facts.run_pilot --provider openai --model gpt-4.1 --modules M0,M1,M3
  python -m stale_facts.run_pilot --provider anthropic --model claude-sonnet-4-5
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from stale_facts.items import pilot_items
from stale_facts.scoring import classify
from stale_facts.summary import summarize


ROOT = Path(__file__).resolve().parents[1]
TOOL_DOCS = {
    "lookup_directory": "Look up the current record in the live directory for this request.",
    "read_skill": "Read the standing skill note for this request.",
    "lookup_forum": "Read the public forum mirror for this request. Forum posts are not verified.",
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall]


class ModelClient:
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        raise NotImplementedError


class OpenAIClient(ModelClient):
    def __init__(self, model: str, api_key: str, base_url: str, temperature: float = 0.7):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, *messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                    },
                }
                for tool in tools
            ],
        }
        data = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        message = data["choices"][0]["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            calls.append(
                ToolCall(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=call["function"].get("arguments") or "{}",
                )
            )
        return Completion(text=message.get("content") or "", tool_calls=calls)


ADAPTION_URL = "https://api.prod.adaptionlabs.ai/api/v1/responses"


def messages_to_adaption_input(messages: list[dict]) -> list[dict]:
    items = []
    for message in messages:
        role = message["role"]
        if role == "user":
            items.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            if message.get("content"):
                items.append({"role": "assistant", "content": message["content"]})
            for call in message.get("tool_calls") or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": call["function"].get("arguments") or "{}",
                    }
                )
        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                }
            )
    return items


class AdaptionClient(ModelClient):
    """Adaption Responses API. Reads ADAPTION_API_KEY. Does not use agentic memory."""

    def __init__(self, model: str, api_key: str, temperature: float = 0.7):
        self.model = model
        self.api_key = api_key
        self.temperature = temperature

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        payload = {
            "model": self.model,
            "instructions": system,
            "input": messages_to_adaption_input(messages),
            "temperature": self.temperature,
            "max_output_tokens": 1024,
            "agentic_memory": False,
            "store": False,
        }
        if tools:
            payload["tool_choice"] = "auto"
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": [],
                    },
                }
                for tool in tools
            ]
        data = _post_json(
            ADAPTION_URL,
            payload,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if data.get("status") == "failed":
            error = data.get("error") or {}
            raise RuntimeError(error.get("message") or "Adaption response failed")
        text = []
        calls = []
        for item in data.get("output") or []:
            if item.get("type") == "function_call":
                calls.append(
                    ToolCall(
                        id=item.get("call_id") or item.get("id") or f"call_{len(calls)}",
                        name=item.get("name") or "",
                        arguments=item.get("arguments") or "{}",
                    )
                )
            elif item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text" and part.get("text"):
                        text.append(part["text"])
        if not text and data.get("output_text") and not calls:
            text.append(data["output_text"])
        return Completion(text="\n".join(text).strip(), tool_calls=calls)


class AnthropicClient(ModelClient):
    def __init__(self, model: str, api_key: str, temperature: float = 0.7):
        self.model = model
        self.api_key = api_key
        self.temperature = temperature

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Completion:
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": self.temperature,
            "system": system,
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": {"type": "object", "properties": {}},
                }
                for tool in tools
            ],
            "messages": messages,
        }
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        text = []
        calls = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=json.dumps(block.get("input") or {}),
                    )
                )
        return Completion(text="\n".join(text).strip(), tool_calls=calls)


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:800]}") from exc


def _tool_specs(names: tuple[str, ...] | list[str]) -> list[dict]:
    return [{"name": name, "description": TOOL_DOCS[name]} for name in names]


def _append_tool_results(provider: str, assistant: Completion, payloads: dict[str, str], messages: list[dict]) -> None:
    if provider == "anthropic":
        content: list[dict] = []
        if assistant.text:
            content.append({"type": "text", "text": assistant.text})
        for call in assistant.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": json.loads(call.arguments or "{}"),
                }
            )
        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": payloads.get(call.name, f"Unknown tool {call.name}."),
                    }
                    for call in assistant.tool_calls
                ],
            }
        )
        return

    messages.append(
        {
            "role": "assistant",
            "content": assistant.text,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments or "{}"},
                }
                for call in assistant.tool_calls
            ],
        }
    )
    for call in assistant.tool_calls:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": payloads.get(call.name, f"Unknown tool {call.name}."),
            }
        )


def run_item(client: ModelClient, item, provider: str, model: str, max_turns: int = 4) -> dict:
    messages = [{"role": "user", "content": item.user}]
    tools = _tool_specs(item.tools)
    called: list[str] = []
    transcript = [{"role": "system", "content": item.system}, {"role": "user", "content": item.user}]
    answer = ""
    for _ in range(max_turns):
        completion = client.complete(item.system, messages, tools)
        if completion.tool_calls:
            for call in completion.tool_calls:
                called.append(call.name)
            _append_tool_results(provider, completion, item.tool_payloads, messages)
            transcript.append(
                {
                    "role": "assistant",
                    "content": completion.text,
                    "tool_calls": [call.name for call in completion.tool_calls],
                }
            )
            transcript.append(
                {
                    "role": "tool",
                    "content": {call.name: item.tool_payloads.get(call.name, "") for call in completion.tool_calls},
                }
            )
            continue
        answer = completion.text
        transcript.append({"role": "assistant", "content": answer})
        break
    else:
        answer = answer or ""
    row = item.to_dict()
    row.pop("tool_payloads", None)
    row.update(
        {
            "provider": provider,
            "model": model,
            "temperature": getattr(client, "temperature", None),
            "answer": answer,
            "tools_called": called,
            "transcript": transcript,
            "scores": classify(item.to_dict(), answer, called),
            "error": None,
        }
    )
    return row


def with_samples(items: list, samples: int) -> list:
    if samples <= 1:
        return items
    return [
        replace(item, id=f"{item.id}#s{index}", sample=index)
        for item in items
        for index in range(samples)
    ]


def select_items(items: list, modules: set[str] | None, limit: int | None) -> list:
    chosen = [item for item in items if modules is None or item.module in modules]
    if limit is not None:
        return chosen[:limit]
    return chosen


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_client(provider: str, model: str, temperature: float = 0.7) -> ModelClient:
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY is not set.")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAIClient(model, key, base, temperature)
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY is not set.")
        return AnthropicClient(model, key, temperature)
    if provider == "adaption":
        key = os.environ.get("ADAPTION_API_KEY")
        if not key:
            raise SystemExit("ADAPTION_API_KEY is not set.")
        return AdaptionClient(model, key, temperature)
    raise SystemExit(f"Unknown provider {provider}. Use adaption, openai, or anthropic.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the silent-corrections pilot.")
    parser.add_argument("--dry-run", action="store_true", help="Write prompts only. No model calls.")
    parser.add_argument("--provider", default=os.environ.get("PILOT_PROVIDER", "adaption"))
    parser.add_argument("--model", default=os.environ.get("PILOT_MODEL", ""))
    parser.add_argument("--modules", default="M0,M1,M3")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--hide-tool-dates", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    modules = {part.strip() for part in args.modules.split(",") if part.strip()}
    items = with_samples(
        select_items(pilot_items(hide_tool_dates=args.hide_tool_dates), modules, args.limit),
        args.samples,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "results" / f"pilot-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    prompts = [item.to_dict() for item in items]
    write_jsonl(out / "prompts.jsonl", prompts)
    counts: dict[str, int] = {}
    for item in items:
        key = f"{item.module}-nudge" if item.nudge else item.module
        counts[key] = counts.get(key, 0) + 1
    print(f"Wrote {len(items)} prompts to {out / 'prompts.jsonl'} ({counts})")
    if args.dry_run:
        return
    if not args.model:
        raise SystemExit("Pass --model. The pilot does not pick a default model.")

    client = make_client(args.provider, args.model, args.temperature)
    rows = []
    for index, item in enumerate(items, start=1):
        print(f"[{index}/{len(items)}] {item.id}", flush=True)
        try:
            rows.append(run_item(client, item, args.provider, args.model))
        except Exception as exc:  # keep the rest of the pilot if one call fails
            failed = item.to_dict()
            failed.update(
                {
                    "provider": args.provider,
                    "model": args.model,
                    "answer": "",
                    "tools_called": [],
                    "transcript": [],
                    "scores": None,
                    "error": str(exc),
                }
            )
            rows.append(failed)
            print(f"  error: {exc}", flush=True)
    write_jsonl(out / "results.jsonl", rows)
    ok = [row for row in rows if not row.get("error")]
    text = summarize(ok)
    (out / "summary.md").write_text(text)
    print(text)
    print(f"Results: {out / 'results.jsonl'}")


if __name__ == "__main__":
    main()
