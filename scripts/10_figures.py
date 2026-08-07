# Figures. Every value is read from results/, never retyped.
#
# All four are built from the CORRECTED population (28 labelled projects), matching the manuscript.
# An earlier version drew figure 1 from the 31-project budget curve while the text reported the
# 28-project one, which would have put a figure and its caption in disagreement.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\10_figures.py
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")
FIG = os.path.join(ROOT, "draft", "figures")
DPI = 600

plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3,
                     "axes.spines.top": False, "axes.spines.right": False})


def load(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return json.load(f)


def save(fig, stem):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(FIG, f"{stem}.{ext}"), dpi=DPI)
    plt.close(fig)
    print(stem)


def fig_size_conditional():
    """The paper's central result deserves the first figure."""
    d = load("corrected.json")["size_conditional"]
    st = d["strata"]
    x = [s["quintile"] for s in st]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.6, 3.2))

    ax1.plot(x, [100 * s["base_rate"] for s in st], marker="o", color="#4d4d4d",
             label="commits with no violation", linewidth=1.4, markersize=4)
    ax1.plot(x, [100 * s["precision"] for s in st], marker="s", color="#b2182b",
             label="commits flagged by a violation", linewidth=1.4, markersize=4)
    ax1.set_xticks(x)
    ax1.set_xlabel("quintile of changed lines")
    ax1.set_ylabel("fault-inducing (%)")
    ax1.legend(frameon=False, fontsize=7.5, loc="upper left")

    ax2.plot(x, [s["lift"] for s in st], marker="o", color="#b2182b",
             linewidth=1.4, markersize=4)
    ax2.axhline(d["pooled"]["lift"], color="#4d4d4d", linestyle="--", linewidth=1.1)
    ax2.text(1.05, d["pooled"]["lift"] + 0.03,
             f"pooled {d['pooled']['lift']:.2f}", color="#4d4d4d", fontsize=8)
    ax2.axhline(1.0, color="#999999", linewidth=0.9)
    ax2.set_xticks(x)
    ax2.set_ylim(0.9, max(2.0, d["pooled"]["lift"] + 0.15))
    ax2.set_xlabel("quintile of changed lines")
    ax2.set_ylabel("lift of the violation flag")
    fig.tight_layout()
    save(fig, "fig1_size_conditional")


def fig_budget_two_units():
    d = load("corrected.json")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.3))

    rows = d["budget_commits"]
    xc = [r["budget_per_1000"] for r in rows]
    for key, marker, ls, col in (("violations", "s", "-", "#b2182b"),
                                 ("churn", "o", "-", "#2166ac"),
                                 ("random", "x", ":", "#999999")):
        ax1.plot(xc, [100 * r[key] for r in rows], marker=marker, linestyle=ls, color=col,
                 label=key, linewidth=1.3, markersize=4)
    ax1.set_xscale("log")
    ax1.set_xticks(xc)
    ax1.set_xticklabels([str(v) for v in xc], fontsize=7.5)
    ax1.set_xlabel("budget: commits reviewed per 1,000")
    ax1.set_ylabel("fault-inducing commits caught (%)")
    ax1.legend(frameon=False, fontsize=7.5, loc="upper left")

    rows = d["budget_lines"]
    xl = [r["budget_per_1000_lines"] for r in rows]
    for key, marker, ls, col in (("smallest commits first", "o", "-", "#2166ac"),
                                 ("violations per line", "s", "-", "#b2182b"),
                                 ("random", "x", ":", "#999999"),
                                 ("churn, raw rank", "^", "--", "#4d4d4d")):
        ax2.plot(xl, [100 * r[key] for r in rows], marker=marker, linestyle=ls, color=col,
                 label=key, linewidth=1.3, markersize=4)
    ax2.set_xscale("log")
    ax2.set_xticks(xl)
    ax2.set_xticklabels([str(v) for v in xl], fontsize=7.5)
    ax2.set_xlabel("budget: changed lines reviewed per 1,000")
    ax2.legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.tight_layout()
    save(fig, "fig2_budget_two_units")


def fig_projects():
    d = load("certification.json")
    per = sorted(d["per_project"], key=lambda s: s["lift"])
    fig, ax = plt.subplots(figsize=(5.4, 6.2))
    colors = ["#b2182b" if s["lift"] <= 1.0 else "#4d4d4d" for s in per]
    ax.barh([s["project"] for s in per], [s["lift"] for s in per], color=colors, height=0.72)
    ax.axvline(1.0, color="#b2182b", linewidth=1.1)
    ax.text(1.03, -0.8, "no better than the base rate", color="#b2182b", fontsize=8)
    ax.set_xlabel("lift over the project's own base rate")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    save(fig, "fig3_per_project_lift")


def fig_rules():
    d = load("rule_screen.json")
    tested = d["all_tested"]
    base = 100 * d["base_rate"]
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    sig = [t for t in tested if t["significant"]]
    ns = [t for t in tested if not t["significant"]]
    ax.scatter([t["alerts_per_1000"] for t in ns], [100 * t["precision"] for t in ns],
               s=14, facecolors="none", edgecolors="#999999", linewidths=0.7,
               label="not significant")
    ax.scatter([t["alerts_per_1000"] for t in sig], [100 * t["precision"] for t in sig],
               s=16, color="#333333", label=f"significant (BH, q={d['q']})")
    ax.axhline(base, color="#b2182b", linewidth=1.1)
    ax.text(0.35, base + 1.4, f"base rate {base:.1f}%", color="#b2182b", fontsize=8)
    ax.axhline(100 * d["useful_precision"], color="#2166ac", linewidth=1.1, linestyle="--")
    ax.text(0.35, 100 * d["useful_precision"] + 1.4, "one alert in two",
            color="#2166ac", fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("alerts per 1,000 commits (log scale)")
    ax.set_ylabel("precision (%)")
    ax.legend(frameon=False, loc="upper right", fontsize=8)
    fig.tight_layout()
    save(fig, "fig4_rule_screen")


def main():
    os.makedirs(FIG, exist_ok=True)
    for old in os.listdir(FIG):
        os.remove(os.path.join(FIG, old))
    fig_size_conditional()
    fig_budget_two_units()
    fig_projects()
    fig_rules()
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
