"""Replace selected rows of a results file with their reruns, and say so in each row.

The first full runs used a 1024-token output limit and did not store the response
status. Some replies came back empty or stopped mid-sentence. Those items were run
again with a higher limit. This writes a merged file and leaves both inputs untouched.

    python -m stale_facts.merge_reruns results/full-X/results.jsonl results/rerun-X/results.jsonl \
        --out results/final-X/results.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def merge(base: list[dict], reruns: list[dict]) -> list[dict]:
    by_id = {row["id"]: row for row in reruns}
    unknown = set(by_id) - {row["id"] for row in base}
    if unknown:
        raise SystemExit(f"Rerun ids not in the base file: {sorted(unknown)}")
    merged = []
    for row in base:
        new = by_id.get(row["id"])
        if new is None:
            # Status was not stored for these rows, so completeness is unknown, not confirmed.
            merged.append({**row, "rerun": False, "incomplete": None})
        else:
            merged.append({**new, "rerun": True, "first_answer": row.get("answer") or ""})
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge rerun rows into a results file.")
    parser.add_argument("base", type=Path)
    parser.add_argument("reruns", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = merge(load(args.base), load(args.reruns))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    rerun = [row for row in rows if row["rerun"]]
    print(f"{len(rows)} rows, {len(rerun)} replaced by reruns, "
          f"{sum(1 for row in rerun if row.get('incomplete'))} of those still incomplete -> {args.out}")


if __name__ == "__main__":
    main()
