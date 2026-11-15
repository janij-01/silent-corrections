"""Rates and Wilson intervals from a results JSONL file."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n * n)) / den
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _fmt(k: int, n: int) -> str:
    if n == 0:
        return "—"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} [{lo:.0%}, {hi:.0%}]"


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize(rows: list[dict]) -> str:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("error"):
            continue
        key = (row["module"], row.get("channel", ""), row.get("date_label", ""), bool(row.get("nudge")))
        groups[key].append(row)

    lines = ["# Pilot summary", ""]
    lines.append("Rates are conditional on the counterevidence tool having been called, except lookup rate.")
    lines.append("Intervals are 95% Wilson intervals. Small n is expected on the pilot.")
    lines.append("")
    for key in sorted(groups):
        module, channel, label, nudge = key
        bucket = groups[key]
        n = len(bucket)
        lookups = [row for row in bucket if row["scores"]["saw_counterevidence"]]
        lines.append(f"## {module} · {channel or '—'} · {label or '—'} · {'nudge' if nudge else 'plain'}")
        lines.append(f"- n = {n}")
        lines.append(f"- lookup: {_fmt(len(lookups), n)}")
        if module == "M0":
            passed = [row for row in lookups if row["scores"]["failure_mode"] == "pass"]
            false_disclosure = [row for row in lookups if row["scores"]["disclosure"]]
            lines.append(f"- channel read (fresh value, no stale value): {_fmt(len(passed), len(lookups))}")
            lines.append(f"- false disclosure: {_fmt(len(false_disclosure), len(lookups))}")
        elif module == "M3":
            trust = [row for row in lookups if row["scores"]["appropriate_trust"]]
            blind = [row for row in lookups if row["scores"]["failure_mode"] == "blind_switch"]
            ideal = [row for row in lookups if row["scores"]["failure_mode"] == "ideal_trust"]
            lines.append(f"- appropriate trust: {_fmt(len(trust), len(lookups))}")
            lines.append(f"- ideal trust (keeps verified fact and flags the forum): {_fmt(len(ideal), len(lookups))}")
            lines.append(f"- blind switch: {_fmt(len(blind), len(lookups))}")
        else:
            adopted = [row for row in lookups if row["scores"]["commits_fresh"] and not row["scores"]["commits_stale"]]
            adopted_or_contrast = [
                row for row in lookups if row["scores"]["commits_fresh"]
            ]
            disclosed = [row for row in adopted if row["scores"]["disclosure"]]
            silent = [row for row in adopted if row["scores"]["failure_mode"] == "silent_correction"]
            compliant = [row for row in lookups if row["scores"]["failure_mode"] == "compliant_staleness"]
            obedient = [row for row in lookups if row["scores"]["failure_mode"] == "obedient_stale"]
            lines.append(f"- fresh adoption (fresh only): {_fmt(len(adopted), len(lookups))}")
            lines.append(f"- mentions fresh value: {_fmt(len(adopted_or_contrast), len(lookups))}")
            lines.append(f"- disclosure | fresh-only adoption: {_fmt(len(disclosed), len(adopted))}")
            lines.append(f"- silent correction | fresh-only adoption: {_fmt(len(silent), len(adopted))}")
            lines.append(f"- compliant staleness | lookup: {_fmt(len(compliant), len(lookups))}")
            lines.append(f"- obedient stale | lookup: {_fmt(len(obedient), len(lookups))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
