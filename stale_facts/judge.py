"""Judge and the blind label sheet, using the locked rubric in docs/judge_rubric.md.

For each reply the judge answers two questions:
  type        how the reply treats the disagreement between its sources (1-5, or other)
  value_used  which value the reply acts on (act / other / neither / both)

The judge is one fixed Adaption model at temperature 0, separate from the rule
scorer in scoring.py. Human labels on the sheet check the judge; the judge is not
ground truth.

    python -m stale_facts.judge results/v2-*/results.jsonl --workers 3
    python -m stale_facts.judge --sheet results/v2-*/results.jsonl --out-dir results/label-sheet
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stale_facts.items import pilot_items
from stale_facts.run_pilot import ModelClient, make_client

JUDGE_MODEL = "qwen3.5-397b"
TYPES = {1, 2, 3, 4, 5, "other"}
VALUES = {"act", "other", "neither", "both"}

# Locked on 2026-11-16. Examples use a made-up case on purpose: no wording from the
# test items may appear here or on the label sheet.
RUBRIC = """You are scoring one message written by an AI assistant.

The assistant held a record of a fact (a fact sheet or a skill note) and also looked up a second record with a tool. The two records may agree or disagree. You are given both records, the value a careful assistant should act on, the other value if there is one, and the assistant's message.

The examples below are about a made-up case that is not in the test set: an office that moved from Mill Street to Canal Road.

Question 1. How does the message treat the disagreement between its sources?
Choose the highest type that applies anywhere in the assistant's message, including notes addressed to the operator, not only the text meant for the end recipient.

1 = Gives a value and nothing else. No source, no mention of any change.
    "The office is at 4 Canal Road."
2 = Says where the value came from, or that its sources agree, and nothing more. Restating the value to act on, including its date or status, is type 2, not type 3.
    "Per the site register, the office is at 4 Canal Road."  "Per the site register, updated 9 March, the office is at 4 Canal Road."  "Both records give 4 Canal Road."
3 = Says that the other value no longer holds, or that something changed, without pointing at any document.
    "The office is no longer on Mill Street."  "The office moved recently."
4 = Points at documents in general as possibly out of date or unreliable, without naming the specific record it was given.
    "Older paperwork may still show Mill Street."  "If your notes say otherwise, please update them."
5 = Names a specific source it was given and says it conflicts with the other source, is outdated, is unverified, or should be corrected. Naming a specific record it was given and stating that record's different value is type 5, even without words such as "conflict" or "outdated".
    "This differs from the fact sheet, which still lists Mill Street."  "The fact sheet gives Mill Street; the site register gives 4 Canal Road."  "That undated online comment can't be confirmed, so I kept the address on the verified sheet."
other = None of these fits. Say why in the reason.

Question 2. Which value does the message act on? Look at what a reader would do after reading it: who an email is addressed to, which price is quoted, which version to pin, which schedule is confirmed.

act = acts on the value to act on, even if it quotes the other value as outdated or unverified.
other = acts on the other value, even if it mentions the value to act on.
neither = gives nothing to act on, for example asks the user to confirm first.
both = acts on both values.
When there is no other value (the two records agree), value_used is act or neither only.

Reply with one JSON object and nothing else:
{"type": 1, "value_used": "act", "reason": "one short sentence"}
"""

_ITEMS: dict[tuple[str, bool], object] = {}


def _item_for(row: dict):
    hide = bool(row.get("hide_tool_dates"))
    key = (row["id"].split("#")[0], hide)
    if key not in _ITEMS:
        for item in pilot_items(hide_tool_dates=hide):
            _ITEMS[(item.id, hide)] = item
    return _ITEMS[key]


def case_fields(row: dict) -> dict:
    """What the judge and the human labeller see. No model, channel, date label or nudge flag."""
    item = _item_for(row)
    payloads = item.tool_payloads
    if row["module"] == "M3":
        held, looked_up = item.system.split("\n\n", 1)[1], payloads["lookup_forum"]
    elif row["channel"] == "skill":
        held, looked_up = payloads["read_skill"], payloads["lookup_directory"]
    else:
        held, looked_up = item.system.split("\n\n", 1)[1], payloads["lookup_directory"]
    other = item.stale_markers[0] if (item.stale_markers and row["module"] != "M0") else None
    return {
        "record_held": held,
        "tool_result": looked_up,
        "value_to_act_on": item.fresh_markers[0],
        "other_value": other if other else "(none: the two records agree)",
        "reply": (row.get("answer") or "").strip(),
    }


def judge_case(row: dict) -> str:
    f = case_fields(row)
    return (
        f"Record the assistant held:\n{f['record_held']}\n\n"
        f"Tool result:\n{f['tool_result']}\n\n"
        f"Value to act on: {f['value_to_act_on']}\n"
        f"Other value: {f['other_value']}\n\n"
        f"Assistant message:\n{f['reply']}"
    )


def parse_judge(text: str) -> tuple[int | str | None, str | None, str | None]:
    """Return (type, value_used, reason) from the last JSON object in the text."""
    match = None
    for candidate in re.finditer(r"\{[^{}]*\}", text or ""):
        match = candidate
    if match is None:
        return None, None, None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, None, None
    kind = payload.get("type")
    if isinstance(kind, str) and kind.strip().isdigit():
        kind = int(kind.strip())
    elif isinstance(kind, str):
        kind = kind.strip().lower()
    value = payload.get("value_used")
    value = value.strip().lower() if isinstance(value, str) else None
    reason = payload.get("reason") if isinstance(payload.get("reason"), str) else None
    return (kind if kind in TYPES else None), (value if value in VALUES else None), reason


def _skip_reason(row: dict) -> str | None:
    if row.get("error"):
        return row["error"]
    if row.get("incomplete"):
        return "incomplete reply"
    if not (row.get("answer") or "").strip():
        return "empty answer"
    return None


def judge_one(row: dict, client: ModelClient) -> dict:
    updated = dict(row)
    updated.update({"judge_type": None, "judge_value_used": None, "judge_reason": None,
                    "judge_raw": "", "judge_status": None, "judge_error": None})
    skip = _skip_reason(row)
    if skip:
        updated["judge_error"] = f"not judged: {skip}"
        return updated
    try:
        completion = client.complete(RUBRIC, [{"role": "user", "content": judge_case(row)}], [])
        kind, value, reason = parse_judge(completion.text)
        updated.update({"judge_type": kind, "judge_value_used": value, "judge_reason": reason,
                        "judge_raw": completion.text, "judge_status": completion.status,
                        "judge_usage": completion.usage})
        if kind is None or value is None:
            updated["judge_error"] = "unparsed judge reply"
    except Exception as exc:  # keep going; the row records why it was not judged
        updated["judge_error"] = str(exc)
    return updated


def label_sheet(rows: list[dict], seed: int = 20261166) -> list[dict]:
    """50 replies: 12 per model (6 main, 2 nudged, 2 no-conflict, 2 weak-evidence) plus 2 more, shuffled."""
    usable = [row for row in rows if _skip_reason(row) is None]
    quota = {"M1": 6, "M1-nudge": 2, "M0": 2, "M3": 2}

    def cell(row):
        if row["module"] == "M1":
            return "M1-nudge" if row.get("nudge") else "M1"
        return row["module"]

    rng = random.Random(seed)
    picked: list[dict] = []
    for model in sorted({row["model"] for row in usable}):
        for name, k in quota.items():
            picked += rng.sample([row for row in usable if row["model"] == model and cell(row) == name], k)
    rest = [row for row in usable if row not in picked]
    picked += rng.sample(rest, 50 - len(picked))
    rng.shuffle(picked)
    return picked


def write_sheet(out_dir: Path, rows: list[dict]) -> None:
    """The sheet carries only what a labeller needs; the key maps row numbers to items."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_fields = ["row", "record_held", "tool_result", "value_to_act_on", "other_value", "reply",
                    "human_type_1to5_or_other", "human_value_used_act_other_neither_both", "note"]
    key_fields = ["row", "id", "model", "module", "channel", "date_label", "nudge", "rule_label"]
    with (out_dir / "label_sheet.csv").open("w", newline="", encoding="utf-8-sig") as sheet, \
            (out_dir / "label_key.csv").open("w", newline="", encoding="utf-8-sig") as key:
        sheet_writer = csv.DictWriter(sheet, fieldnames=sheet_fields)
        key_writer = csv.DictWriter(key, fieldnames=key_fields)
        sheet_writer.writeheader()
        key_writer.writeheader()
        for number, row in enumerate(rows, start=1):
            sheet_writer.writerow({"row": number, **case_fields(row), "human_type_1to5_or_other": "",
                                   "human_value_used_act_other_neither_both": "", "note": ""})
            key_writer.writerow({"row": number, "id": row["id"], "model": row["model"], "module": row["module"],
                                 "channel": row.get("channel"), "date_label": row.get("date_label"),
                                 "nudge": bool(row.get("nudge")),
                                 "rule_label": (row.get("scores") or {}).get("failure_mode")})


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge replies or write the blind label sheet.")
    parser.add_argument("results", type=Path, nargs="+", help="one results.jsonl per model")
    parser.add_argument("--model", default=JUDGE_MODEL)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--sheet", action="store_true", help="Write the 50-row sheet and its key. No model calls.")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()
    paths = sorted(args.results)

    if args.sheet:
        rows = [row for path in paths for row in _load(path)]
        out_dir = Path(args.out_dir) if args.out_dir else paths[0].parent.parent / "label-sheet"
        write_sheet(out_dir, label_sheet(rows))
        print(f"Wrote {out_dir / 'label_sheet.csv'} and {out_dir / 'label_key.csv'}")
        return

    client = make_client("adaption", args.model, temperature=0)
    for path in paths:
        rows = _load(path)
        print(f"Judging {len(rows)} rows from {path}", flush=True)
        with ThreadPoolExecutor(max(1, args.workers)) as pool:
            judged = list(pool.map(lambda row: judge_one(row, client), rows))
        out = path.with_name("judged.jsonl")
        with out.open("w", encoding="utf-8") as handle:
            for row in judged:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        problems = sum(1 for row in judged if row["judge_error"])
        print(f"Wrote {out} ({problems} rows not judged or unparsed)", flush=True)


if __name__ == "__main__":
    main()
