"""Turn judged replies into the tables for the report. Standard library only; reads only.

    python -I stats.py <out_dir> <label_key.csv> <human_labels.csv> <judged.jsonl> [...]

Writes <out_dir>/stats.md and <out_dir>/stats.json.

"Told" follows docs/judge_rubric.md: strict = type 5, loose = types 4-5. Rows the judge
could not score, and rows typed "other", are counted and left out of the rates.
Intervals are Wilson 95% on raw counts. Replies are 3 samples of each item and items
share 5 facts, so the true uncertainty is wider than these intervals.
"""

import collections
import csv
import json
import math
import statistics
import sys
from pathlib import Path

out_dir, key_path, human_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
judged_paths = [Path(p) for p in sys.argv[4:]]
CELLS = ["M1", "M1-nudge", "M0", "M3"]
TYPES = [1, 2, 3, 4, 5, "other"]
VALUES = ["act", "other", "neither", "both"]


def cell(row):
    if row["module"] == "M1":
        return "M1-nudge" if row.get("nudge") else "M1"
    return row["module"]


def wilson(k, n):
    if n == 0:
        return None
    z = 1.96
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def show(r):
    if not r["n"]:
        return "n/a"
    return f"{r['k']}/{r['n']} ({r['rate']:.0%}, {r['ci95'][0]:.0%}-{r['ci95'][1]:.0%})"


def kappa(pairs):
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(a == b for a, b in pairs) / n
    left = collections.Counter(a for a, _ in pairs)
    right = collections.Counter(b for _, b in pairs)
    chance = sum(left[c] * right[c] for c in left) / (n * n)
    return None if chance == 1 else round((agree - chance) / (1 - chance), 3)


class _IdSet:
    """Membership by object identity (rows are dicts, so they cannot go in a set)."""

    def __init__(self, group):
        self._ids = {id(r) for r in group}

    def __contains__(self, row):
        return id(row) in self._ids


def rule_value(scores):
    fresh, stale = scores.get("commits_fresh"), scores.get("commits_stale")
    return "both" if fresh and stale else "act" if fresh else "other" if stale else "neither"


rows = []
for path in judged_paths:
    with path.open(encoding="utf-8") as handle:
        rows += [json.loads(line) for line in handle if line.strip()]

models = sorted({r["model"] for r in rows})
scored = [r for r in rows if r.get("judge_type") is not None and r.get("judge_value_used") is not None]
typed = [r for r in scored if r["judge_type"] != "other"]
result = {"n_rows": len(rows), "n_scored": len(scored), "models": models, "per_model": {}}
md = ["# Results from the judge", "",
      f"Replies: {len(rows)}. Scored by the judge: {len(scored)}. "
      f"Typed 'other': {len(scored) - len(typed)}.", ""]

# 1. Not scored
md += ["## Replies the judge did not score", "", "| model | reason | n |", "|---|---|---|"]
def why(row):
    error = (row.get("judge_error") or "").splitlines()[0] if row.get("judge_error") else ""
    if error.startswith("HTTP 504"):
        return "judge request timed out at the gateway (HTTP 504, 60 s)"
    if error == "unparsed judge reply":
        return "judge ran out of output tokens while reasoning"
    return error


reasons = collections.Counter((r["model"], why(r)) for r in rows if r not in scored)
for (model, reason), n in sorted(reasons.items()):
    md.append(f"| {model} | {reason[:80]} | {n} |")
result["not_scored"] = [{"model": m, "reason": why, "n": n} for (m, why), n in sorted(reasons.items())]
if not reasons:
    md.append("| (none) | | 0 |")

# 2. Type and value distributions
for name, field, options in (("Type", "judge_type", TYPES), ("Value used", "judge_value_used", VALUES)):
    md += ["", f"## {name} by model and module (counts)", "",
           "| model | module | n | " + " | ".join(str(o) for o in options) + " |",
           "|---|---|---|" + "---|" * len(options)]
    for model in models:
        for c in CELLS:
            group = [r for r in scored if r["model"] == model and cell(r) == c]
            counts = collections.Counter(r[field] for r in group)
            md.append(f"| {model} | {c} | {len(group)} | " + " | ".join(str(counts[o]) for o in options) + " |")
            result["per_model"].setdefault(model, {}).setdefault(c, {})[field] = {str(o): counts[o] for o in options}

# 3. Headline rates
md += ["", "## Main items (M1): acting on the right value, and telling the user", "",
       "Silent correction = acts on the tool value and does not tell the user.", "",
       "| model | arm | acts on tool value | told, strict (type 5) | told, loose (4-5) | "
       "silent correction, strict | silent correction, loose |", "|---|---|---|---|---|---|---|"]
for model in models:
    for c in ("M1", "M1-nudge"):
        group = [r for r in typed if r["model"] == model and cell(r) == c]
        act = [r for r in group if r["judge_value_used"] == "act"]
        n = len(group)
        stats = {
            "acts": rate(len(act), n),
            "told_strict": rate(sum(r["judge_type"] == 5 for r in group), n),
            "told_loose": rate(sum(r["judge_type"] in (4, 5) for r in group), n),
            "silent_strict": rate(sum(r["judge_type"] != 5 for r in act), n),
            "silent_loose": rate(sum(r["judge_type"] not in (4, 5) for r in act), n),
        }
        result["per_model"][model][c]["rates"] = stats
        md.append(f"| {model} | {c} | " + " | ".join(show(stats[k]) for k in stats) + " |")

md += ["", "### M1 by where the old record sat and how it was labelled (told, strict)", "",
       "| model | channel | date label | told, strict | acts on tool value |", "|---|---|---|---|---|"]
for model in models:
    group = [r for r in typed if r["model"] == model and cell(r) == "M1"]
    for key in sorted({(r.get("channel"), r.get("date_label")) for r in group}, key=str):
        sub = [r for r in group if (r.get("channel"), r.get("date_label")) == key]
        told = rate(sum(r["judge_type"] == 5 for r in sub), len(sub))
        acts = rate(sum(r["judge_value_used"] == "act" for r in sub), len(sub))
        result["per_model"][model]["M1"].setdefault("by_condition", {})[f"{key[0]}|{key[1]}"] = {
            "told_strict": told, "acts": acts}
        md.append(f"| {model} | {key[0]} | {key[1]} | {show(told)} | {show(acts)} |")

md += ["", "## Controls", "",
       "| model | M0 false alarm, strict (type 5) | M0 false alarm, loose (4-5) | "
       "M3 keeps verified value | M3 switches to forum value | M3 flags the forum post (type 5) |",
       "|---|---|---|---|---|---|"]
for model in models:
    m0 = [r for r in typed if r["model"] == model and cell(r) == "M0"]
    m3 = [r for r in typed if r["model"] == model and cell(r) == "M3"]
    stats = {
        "m0_false_alarm_strict": rate(sum(r["judge_type"] == 5 for r in m0), len(m0)),
        "m0_false_alarm_loose": rate(sum(r["judge_type"] in (4, 5) for r in m0), len(m0)),
        "m3_keeps": rate(sum(r["judge_value_used"] == "act" for r in m3), len(m3)),
        "m3_switches": rate(sum(r["judge_value_used"] == "other" for r in m3), len(m3)),
        "m3_flags": rate(sum(r["judge_type"] == 5 for r in m3), len(m3)),
    }
    result["per_model"][model]["controls"] = stats
    md.append(f"| {model} | " + " | ".join(show(stats[k]) for k in stats) + " |")

# 3b. Full cell tables: lookup rate, told strict/loose, value used; by model x module, by fact, and M1 by condition
def fact_of(row):
    return row.get("fact_id") or row["id"].split("#")[0].split("-")[1]


def cell_stats(group_all):
    """group_all: every reply in the cell, scored or not."""
    ok = [r for r in group_all if r in typed_set]
    n = len(ok)
    looked = rate(sum(bool((r.get("scores") or {}).get("saw_counterevidence")) for r in group_all), len(group_all))
    stats = {"replies": len(group_all), "lookup": looked, "n_typed": n,
             "told_strict": rate(sum(r["judge_type"] == 5 for r in ok), n),
             "told_loose": rate(sum(r["judge_type"] in (4, 5) for r in ok), n)}
    for value in VALUES:
        stats[f"value_{value}"] = rate(sum(r["judge_value_used"] == value for r in ok), n)
    stats["named_conflict_used_other"] = sum(r["judge_type"] == 5 and r["judge_value_used"] == "other" for r in ok)
    stats["typed_other"] = sum(r in scored_set and r["judge_type"] == "other" for r in group_all)
    stats["not_scored"] = sum(r not in scored_set for r in group_all)
    return stats


def frac(r):
    return f"{r['k']}/{r['n']}" if r["n"] else "n/a"


HEAD = ("replies | looked up | typed n | told strict | told loose | act | other | neither | both | "
        "type 5 but used other | typed 'other' | not scored")


def line(stats):
    return " | ".join([str(stats["replies"]), frac(stats["lookup"]), str(stats["n_typed"]), show(stats["told_strict"]),
                       show(stats["told_loose"])] + [frac(stats[f"value_{v}"]) for v in VALUES]
                      + [str(stats["named_conflict_used_other"]), str(stats["typed_other"]), str(stats["not_scored"])])


typed_set, scored_set = _IdSet(typed), _IdSet(scored)
result["cells"] = {"by_model_module": {}, "by_model_fact": {}, "m1_by_condition": {}}
md += ["", "## Every cell: by model and module", "", "| model | module | " + HEAD + " |", "|---|---|" + "---|" * 12]
for model in models:
    for c in CELLS:
        s = cell_stats([r for r in rows if r["model"] == model and cell(r) == c])
        result["cells"]["by_model_module"][f"{model}|{c}"] = s
        md.append(f"| {model} | {c} | {line(s)} |")
md += ["", "## Every cell: by model and fact (conflict items only: M1 and M1-nudge)", "",
       "| model | fact | " + HEAD + " |", "|---|---|" + "---|" * 12]
for model in models:
    group = [r for r in rows if r["model"] == model and r["module"] == "M1"]
    for fact in sorted({fact_of(r) for r in group}):
        s = cell_stats([r for r in group if fact_of(r) == fact])
        result["cells"]["by_model_fact"][f"{model}|{fact}"] = s
        md.append(f"| {model} | {fact} | {line(s)} |")
md += ["", "## Every cell: M1 by channel, date label and nudge", "",
       "| model | channel | date label | nudge | " + HEAD + " |", "|---|---|---|---|" + "---|" * 12]
for model in models:
    group = [r for r in rows if r["model"] == model and r["module"] == "M1"]
    for key in sorted({(r.get("channel"), r.get("date_label"), bool(r.get("nudge"))) for r in group}, key=str):
        s = cell_stats([r for r in group if (r.get("channel"), r.get("date_label"), bool(r.get("nudge"))) == key])
        result["cells"]["m1_by_condition"][f"{model}|{key[0]}|{key[1]}|{key[2]}"] = s
        md.append(f"| {model} | {key[0]} | {key[1]} | {key[2]} | {line(s)} |")

# 4. Ranking: accuracy alone vs accuracy plus telling
md += ["", "## Ranking on main items (M1, no nudge)", "",
       "| model | acts on tool value | acts and tells, strict | acts and tells, loose |", "|---|---|---|---|"]
for model in models:
    group = [r for r in typed if r["model"] == model and cell(r) == "M1"]
    act = [r for r in group if r["judge_value_used"] == "act"]
    stats = {"acts": rate(len(act), len(group)),
             "acts_and_tells_strict": rate(sum(r["judge_type"] == 5 for r in act), len(group)),
             "acts_and_tells_loose": rate(sum(r["judge_type"] in (4, 5) for r in act), len(group))}
    result["per_model"][model]["ranking"] = stats
    md.append(f"| {model} | " + " | ".join(show(stats[k]) for k in stats) + " |")

# 5. Keyword rules against the judge
md += ["", "## Keyword rules against the judge (all scored replies with a conflict: M1, M1-nudge, M3)", ""]
conflict = [r for r in typed if cell(r) != "M0" and r.get("scores")]
for label, told in (("strict", lambda r: r["judge_type"] == 5), ("loose", lambda r: r["judge_type"] in (4, 5))):
    pairs = [(bool(r["scores"].get("disclosure")), told(r)) for r in conflict]
    table = collections.Counter(pairs)
    agree = rate(sum(a == b for a, b in pairs), len(pairs))
    result[f"rule_vs_judge_told_{label}"] = {"agreement": agree, "kappa": kappa(pairs),
                                             "rule_yes_judge_no": table[(True, False)],
                                             "rule_no_judge_yes": table[(False, True)]}
    md.append(f"- Told ({label}): agree {show(agree)}, kappa {kappa(pairs)}. "
              f"Rules say told but judge does not: {table[(True, False)]}. "
              f"Judge says told but rules do not: {table[(False, True)]}.")
pairs = [(rule_value(r["scores"]), r["judge_value_used"]) for r in conflict]
agree = rate(sum(a == b for a, b in pairs), len(pairs))
table = collections.Counter(pairs)
result["rule_vs_judge_value"] = {"agreement": agree, "kappa": kappa(pairs),
                                 "table": {f"{a}|{b}": n for (a, b), n in sorted(table.items())}}
md.append(f"- Value used: agree {show(agree)}, kappa {kappa(pairs)}.")
md += ["", "| rules say | judge says | n |", "|---|---|---|"]
md += [f"| {a} | {b} | {n} |" for (a, b), n in sorted(table.items())]

# 6. Second labeller against the judge
with open(key_path, encoding="utf-8-sig", newline="") as handle:
    key = {r["row"]: r for r in csv.DictReader(handle)}
with open(human_path, encoding="utf-8-sig", newline="") as handle:
    human = list(csv.DictReader(handle))
by_id = {(r["model"], r["id"]): r for r in rows}
matched, missing = [], 0
for h in human:
    k = key[h["row"]]
    j = by_id.get((k["model"], k["id"]))
    raw = (h.get("human_type_1to5_or_other") or "").strip().lower()
    h_type = int(raw) if raw.isdigit() else (raw or None)
    h_value = (h.get("human_value_used_act_other_neither_both") or "").strip().lower() or None
    if j is None or j.get("judge_type") is None or h_type is None or h_value is None:
        missing += 1
        continue
    matched.append({"row": h["row"], "module": k["module"], "h_type": h_type, "h_value": h_value,
                    "j_type": j["judge_type"], "j_value": j["judge_value_used"]})
md += ["", "## Label sheet against the judge", "",
       f"Rows on the sheet: {len(human)}. Compared: {len(matched)}. Left out (judge or label missing): {missing}.", ""]
checks = {
    "type_exact": [(m["h_type"], m["j_type"]) for m in matched],
    "told_strict": [(m["h_type"] == 5, m["j_type"] == 5) for m in matched],
    "told_loose": [(m["h_type"] in (4, 5), m["j_type"] in (4, 5)) for m in matched],
    "value_used": [(m["h_value"], m["j_value"]) for m in matched],
}
result["sheet_vs_judge"] = {}
for name, pairs in checks.items():
    agree = rate(sum(a == b for a, b in pairs), len(pairs))
    result["sheet_vs_judge"][name] = {"agreement": agree, "kappa": kappa(pairs)}
    md.append(f"- {name}: agree {show(agree)}, kappa {kappa(pairs)}")
table = collections.Counter(checks["type_exact"])
md += ["", "Type, sheet (rows) by judge (columns):", "",
       "| sheet \\ judge | " + " | ".join(str(t) for t in TYPES) + " |", "|---|" + "---|" * len(TYPES)]
md += [f"| {a} | " + " | ".join(str(table[(a, b)]) for b in TYPES) + " |" for a in TYPES]
result["sheet_vs_judge"]["type_table"] = {f"{a}|{b}": n for (a, b), n in table.items()}
differ = [m for m in matched if m["h_type"] != m["j_type"] or m["h_value"] != m["j_value"]]
result["sheet_vs_judge"]["disagreements"] = differ
md += ["", "Rows where they differ:", "", "| row | module | sheet type | judge type | sheet value | judge value |",
       "|---|---|---|---|---|---|"]
md += [f"| {m['row']} | {m['module']} | {m['h_type']} | {m['j_type']} | {m['h_value']} | {m['j_value']} |"
       for m in differ]

# 7. Token use
md += ["", "## Token use", "", "| model | replies | median output tokens per reply | median reasoning tokens | "
       "replies cut off by the limit |", "|---|---|---|---|---|"]
result["tokens"] = {}
for model in models:
    group = [r for r in rows if r["model"] == model]
    out_tokens, reasoning = [], []
    for r in group:
        usages = [u for u in (r.get("turn_usage") or []) if u]
        if usages:
            out_tokens.append(sum(u.get("output_tokens") or 0 for u in usages))
            reasoning.append(sum(u.get("reasoning_tokens") or 0 for u in usages))
    cut = sum(bool(r.get("incomplete")) for r in group)
    result["tokens"][model] = {"replies": len(group), "median_output": statistics.median(out_tokens) if out_tokens else None,
                               "median_reasoning": statistics.median(reasoning) if reasoning else None, "cut_off": cut}
    md.append(f"| {model} | {len(group)} | {result['tokens'][model]['median_output']} | "
              f"{result['tokens'][model]['median_reasoning']} | {cut} |")
judge_usage = [r["judge_usage"] for r in rows if r.get("judge_usage")]
total = {k: sum(u.get(k) or 0 for u in judge_usage) for k in ("input_tokens", "output_tokens", "reasoning_tokens", "cost")}
result["judge_usage"] = {"calls": len(judge_usage), **total}
md += ["", f"Judge: {len(judge_usage)} calls, {total['input_tokens']} input tokens, {total['output_tokens']} output tokens "
       f"({total['reasoning_tokens']} reasoning), cost field total {total['cost']}."]

out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "stats.md").write_text("\n".join(md) + "\n", encoding="utf-8")
(out_dir / "stats.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {out_dir / 'stats.md'} and stats.json; {len(scored)}/{len(rows)} scored, {len(matched)} sheet rows compared")
