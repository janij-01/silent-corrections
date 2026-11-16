"""Figures and tables for the Silent Corrections report, from the judge output.

    python make_figures.py results/v2-*/judged.jsonl [more judged.jsonl ...] --out figs/

Rates follow Section 3.4 of the report:
- M1 and M3 rates are conditional on a lookup of the counterevidence tool.
- "New value used" = judge_value_used == "act" among looked-up, judged replies.
- Strict disclosure = judge_type == 5; loose = judge_type in {4, 5};
  both among replies with judge_value_used == "act". judge_type "other" is left out of both.
- Rows with a judge_error (not judged, unparsed) are counted and excluded.
All intervals are 95% Wilson intervals.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reference palette (dataviz skill), validated on a white surface:
# categorical slots 1-3 pass all checks; aqua is below 3:1, so every bar carries a printed value.
C_NEW, C_LOOSE, C_STRICT = "#2a78d6", "#eb6834", "#1baf7a"
# Ordinal blue ramp for types 1-5, validated with --ordinal.
TYPE_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "savefig.dpi": 300, "savefig.bbox": "tight",
})


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, c - m), min(1.0, c + m)


def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            rows += [json.loads(l) for l in fh if l.strip()]
    return rows


def norm_type(t):
    if isinstance(t, str) and t.strip().isdigit():
        return int(t)
    return t


def looked_up(r):
    need = "lookup_forum" if r["module"] == "M3" else "lookup_directory"
    return need in (r.get("tools_called") or [])


def cell_rates(rs):
    """rs: judged, looked-up rows of one cell."""
    n = len(rs)
    act = [r for r in rs if r["judge_value_used"] == "act"]
    typed = [r for r in act if norm_type(r["judge_type"]) != "other"]
    k_strict = sum(norm_type(r["judge_type"]) == 5 for r in typed)
    k_loose = sum(norm_type(r["judge_type"]) in (4, 5) for r in typed)
    vu = Counter(r["judge_value_used"] for r in rs)
    other_named = sum(r["judge_value_used"] == "other" and norm_type(r["judge_type"]) == 5 for r in rs)
    return {
        "n": n, "act": len(act), "new_value": wilson(len(act), n),
        "strict": wilson(k_strict, len(typed)), "loose": wilson(k_loose, len(typed)),
        "k_strict": k_strict, "k_loose": k_loose, "n_typed": len(typed),
        "vu": vu, "other_conflict_named": other_named,
        "type_other": sum(norm_type(r["judge_type"]) == "other" for r in rs),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("judged", nargs="+")
    ap.add_argument("--out", default="figs")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = load(a.judged)

    errors = [r for r in rows if r.get("judge_error")]
    ok = [r for r in rows if not r.get("judge_error")]
    models = sorted({r["model"] for r in rows})
    print(f"rows {len(rows)}, judged {len(ok)}, not judged/unparsed {len(errors)}")

    # ---------- tables ----------
    groups = defaultdict(list)
    lookup = defaultdict(lambda: [0, 0])
    for r in rows:
        key = (r["model"], r["module"], r.get("channel", ""), r.get("date_label", ""), bool(r.get("nudge")), r.get("fact_id", ""))
        lookup[key][1] += 1
        if looked_up(r):
            lookup[key][0] += 1
            if not r.get("judge_error"):
                groups[key].append(r)

    def agg(pred):
        rs = [r for k, v in groups.items() if pred(k) for r in v]
        lk = [v for k, v in lookup.items() if pred(k)]
        return cell_rates(rs), (sum(x[0] for x in lk), sum(x[1] for x in lk))

    table_specs = []
    for m in models + ["ALL"]:
        for mod, nudge in (("M0", False), ("M1", False), ("M1", True), ("M3", False)):
            table_specs.append((f"{m} | {mod}{' nudge' if nudge else ''}",
                                lambda k, m=m, mod=mod, nudge=nudge: (m == "ALL" or k[0] == m) and k[1] == mod and k[4] == nudge))
    for ch in ("system", "skill"):
        for lab in ("undated", "authoritative"):
            for nudge in (False, True):
                if nudge and lab == "undated":
                    continue
                table_specs.append((f"ALL | M1 {ch} {lab}{' nudge' if nudge else ''}",
                                    lambda k, ch=ch, lab=lab, nudge=nudge: k[1] == "M1" and k[2] == ch and k[3] == lab and k[4] == nudge))
    for fact in sorted({k[5] for k in lookup}):
        table_specs.append((f"ALL | M1 plain fact={fact}", lambda k, fact=fact: k[1] == "M1" and not k[4] and k[5] == fact))

    with open(out / "rates.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cell", "lookup_k", "lookup_n", "n_judged", "act", "other", "neither", "both",
                    "new_value_rate", "nv_lo", "nv_hi", "strict_k", "loose_k", "n_typed",
                    "strict", "strict_lo", "strict_hi", "loose", "loose_lo", "loose_hi",
                    "other_value_conflict_named", "type_other"])
        for name, pred in table_specs:
            c, (lk, ln) = agg(pred)
            w.writerow([name, lk, ln, c["n"], c["vu"]["act"], c["vu"]["other"], c["vu"]["neither"], c["vu"]["both"],
                        *[f"{x:.3f}" for x in c["new_value"]], c["k_strict"], c["k_loose"], c["n_typed"],
                        *[f"{x:.3f}" for x in c["strict"]], *[f"{x:.3f}" for x in c["loose"]],
                        c["other_conflict_named"], c["type_other"]])
    print("wrote", out / "rates.csv")

    # ---------- Figure 1: M1 plain, per model ----------
    fig, ax = plt.subplots(figsize=(6.3, 2.8))
    metrics = [("new_value", "New value used", C_NEW), ("loose", "Loose disclosure (types 4-5)", C_LOOSE),
               ("strict", "Strict disclosure (type 5)", C_STRICT)]
    width = 0.26
    for i, m in enumerate(models):
        c, _ = agg(lambda k, m=m: k[0] == m and k[1] == "M1" and not k[4])
        for j, (key, label, col) in enumerate(metrics):
            p, lo, hi = c[key]
            x = i + (j - 1) * (width + 0.02)
            ax.bar(x, p, width, color=col, label=label if i == 0 else None, zorder=2)
            ax.errorbar(x, p, yerr=[[max(0, p - lo)], [max(0, hi - p)]], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=2, zorder=3)
            ax.text(x, min(hi, 1) + 0.03, f"{p:.0%}", ha="center", va="bottom", fontsize=7, color=INK)
    ax.set_xticks(range(len(models)), models)
    ax.set_ylim(0, 1.18); ax.set_yticks([0, .25, .5, .75, 1], ["0%", "25%", "50%", "75%", "100%"])
    ax.yaxis.grid(True, color=GRID, lw=0.6, zorder=0)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.16), fontsize=8)
    ax.set_ylabel("Share of looked-up replies")
    fig.savefig(out / "fig1_gap_by_model.pdf"); fig.savefig(out / "fig1_gap_by_model.png")
    plt.close(fig)

    # ---------- Figure 2: M1 conditions, one panel per model (strict disclosure) ----------
    conds = [("system", "undated", False, "System prompt, undated"),
             ("system", "authoritative", False, "System prompt, 'source of truth'"),
             ("system", "authoritative", True, "  + source-note nudge"),
             ("skill", "undated", False, "Skill file, undated"),
             ("skill", "authoritative", False, "Skill file, 'source of truth'"),
             ("skill", "authoritative", True, "  + source-note nudge")]
    fig, axes = plt.subplots(1, len(models), figsize=(7.0, 2.5), sharey=True)
    for ax, m in zip(axes, models):
        for i, (ch, lab, nudge, name) in enumerate(conds):
            c, _ = agg(lambda k, m=m, ch=ch, lab=lab, nudge=nudge: k[0] == m and k[1] == "M1" and k[2] == ch and k[3] == lab and k[4] == nudge)
            y = len(conds) - 1 - i
            p, lo, hi = c["strict"]
            ax.plot([lo, hi], [y, y], color=C_NEW, lw=1.6, solid_capstyle="round", zorder=2)
            ax.plot(p, y, "o", ms=5, color=C_NEW, mec="white", mew=1, zorder=3)
            ax.text(1.04, y, f"{c['k_strict']}/{c['n_typed']}", va="center", fontsize=6.5, color=INK2,
                    transform=ax.get_yaxis_transform())
        ax.axhline(2.5, color=GRID, lw=0.8, zorder=0)
        ax.set_title(m, fontsize=8, color=INK)
        ax.set_xlim(0, 1); ax.set_xticks([0, .5, 1], ["0", "50", "100"], fontsize=7)
        ax.xaxis.grid(True, color=GRID, lw=0.6, zorder=0)
    axes[0].set_yticks(range(len(conds)), [c[3] for c in conds][::-1], fontsize=7)
    fig.supxlabel("Strict disclosure (%) among replies that act on the tool value, with 95% Wilson intervals", fontsize=8, y=-0.06)
    fig.subplots_adjust(wspace=0.55)
    fig.savefig(out / "fig2_disclosure_by_condition.pdf"); fig.savefig(out / "fig2_disclosure_by_condition.png")
    plt.close(fig)

    # ---------- Figure A: type distribution per model, M1 plain ----------
    fig, ax = plt.subplots(figsize=(6.3, 2.0))
    for i, m in enumerate(models):
        rs = [r for k, v in groups.items() if k[0] == m and k[1] == "M1" and not k[4] for r in v]
        cnt = Counter(norm_type(r["judge_type"]) for r in rs)
        n = sum(cnt.values()) or 1
        left = 0
        for t, col in zip((1, 2, 3, 4, 5), TYPE_RAMP):
            share = cnt[t] / n
            ax.barh(i, share, left=left, color=col, edgecolor="white", linewidth=1, height=0.6,
                    label=f"Type {t}" if i == 0 else None)
            if share >= 0.07:
                ax.text(left + share / 2, i, f"{share:.0%}", ha="center", va="center", fontsize=7,
                        color="white" if t >= 3 else INK)
            left += share
        if cnt["other"]:
            ax.text(1.01, i, f"other {cnt['other']}", va="center", fontsize=7, color=INK2)
    ax.set_yticks(range(len(models)), models, fontsize=8); ax.invert_yaxis()
    ax.set_xlim(0, 1); ax.set_xticks([0, .5, 1], ["0%", "50%", "100%"])
    ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.3), fontsize=7)
    fig.savefig(out / "figA_type_distribution.pdf"); fig.savefig(out / "figA_type_distribution.png")
    plt.close(fig)
    print("wrote figures to", out)


if __name__ == "__main__":
    main()
