# The corrected primary analysis, after review round 1.
#
# Two changes of population and one change of question, all forced by the review:
#
#   POPULATION. The primary population is now the 28 projects that carry at least one SZZ label.
#   Three projects (hive, commons-exec, commons-ognl) have none, so every commit in them is a
#   guaranteed false positive. They are 10.5 percent of commits and supply 50.9 percent of the
#   violations, which is why including them reversed the severity result. The 31-project figures are
#   retained as a sensitivity condition, not as the headline.
#
#   UNIT. The budget curve is reported twice: denominated in commits reviewed, and denominated in
#   changed lines reviewed. The second is the effort-aware unit. Reporting only the first while the
#   winning policy ranks on commit size is the precise error the effort-aware literature exists to
#   condemn.
#
#   QUESTION. The headline is no longer "what does the violation flag predict" but "what does it add
#   once you know how large the commit is". Those are different questions and only the second is
#   about static analysis.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\15_corrected.py
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "corrected.json")

SEED = 20260808
N_BOOT = 2000
BUDGETS = [5, 10, 25, 50, 100, 200, 300, 500]
SEVERITIES = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
TYPES = ["BUG", "VULNERABILITY", "CODE_SMELL"]


def load(cur):
    sev_cols = ",\n".join(
        f"SUM(CASE WHEN i.SEVERITY='{s}' THEN 1 ELSE 0 END) sev_{s.lower()}"
        for s in SEVERITIES)
    type_cols = ",\n".join(
        f"SUM(CASE WHEN i.TYPE='{t}' THEN 1 ELSE 0 END) typ_{t.lower()}"
        for t in TYPES)
    return cur.execute(f"""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH GROUP BY g.COMMIT_HASH
        ),
        viol AS (
            SELECT a.REVISION h, COUNT(*) k, {sev_cols}, {type_cols}
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        ),
        churn AS (
            SELECT COMMIT_HASH h, SUM(COALESCE(LINES_ADDED,0)+COALESCE(LINES_REMOVED,0)) c
            FROM GIT_COMMITS_CHANGES GROUP BY COMMIT_HASH
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT p.PROJECT_KEY proj, COALESCE(v.k,0) nviol,
               {", ".join(f"COALESCE(v.sev_{s.lower()},0) sev_{s.lower()}" for s in SEVERITIES)},
               {", ".join(f"COALESCE(v.typ_{t.lower()},0) typ_{t.lower()}" for t in TYPES)},
               COALESCE(ch.c,0) churn,
               CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END y
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN viol v ON v.h = gate.h
        LEFT JOIN churn ch ON ch.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
    """).fetchall()


def score(flag, y):
    fl, pos, n = int(flag.sum()), int(y.sum()), len(y)
    tp = int((flag & y).sum())
    base = pos / n if n else 0.0
    return {"n": n, "flagged": fl, "tp": tp, "base_rate": base,
            "precision": tp / fl if fl else 0.0,
            "recall": tp / pos if pos else 0.0,
            "alerts_per_1000": 1000 * fl / n if n else 0.0,
            "lift": ((tp / fl) / base) if fl and base else 0.0}


def recall_at_cost(scores, y, cost, budget):
    """Recall when items are taken in descending score order until `budget` of cost is spent.

    Ties are resolved by EXPECTATION, not by row order. This matters more than it sounds: 45,458 of
    the 60,489 commits introduce no violation at all and therefore tie at zero, so a naive sort hands
    the violation ranking whatever order the database happened to return. Review round two found the
    earlier implementation doing exactly that, and the error on the 500-per-thousand row was 11.3
    percentage points.
    """
    total_pos = int(y.sum())
    if budget <= 0 or total_pos == 0:
        return 0.0
    order = np.argsort(-scores, kind="stable")
    s_sorted, c_sorted, y_sorted = scores[order], cost[order], y[order]
    spent = np.cumsum(c_sorted)
    k = int(np.searchsorted(spent, budget, side="right"))
    if k >= len(y_sorted):
        return 1.0
    cut = s_sorted[k] if k < len(s_sorted) else s_sorted[-1]

    strictly_above = scores > cut
    caught = int(y[strictly_above].sum())
    spent_above = float(cost[strictly_above].sum())

    tied = scores == cut
    if not tied.any():
        return caught / total_pos
    remaining = budget - spent_above
    tied_cost = float(cost[tied].sum())
    if tied_cost <= 0:
        return min(1.0, (caught + int(y[tied].sum())) / total_pos)
    share = max(0.0, min(1.0, remaining / tied_cost))
    return min(1.0, (caught + share * int(y[tied].sum())) / total_pos)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    r = load(con.cursor())
    con.close()
    rng = np.random.default_rng(SEED)

    proj = np.array([x["proj"] for x in r])
    y = np.array([x["y"] for x in r], dtype=bool)
    nviol = np.array([x["nviol"] for x in r], dtype=float)
    churn = np.array([x["churn"] for x in r], dtype=float)
    sev = {s: np.array([x[f"sev_{s.lower()}"] for x in r], dtype=float) for s in SEVERITIES}
    typ = {t: np.array([x[f"typ_{t.lower()}"] for x in r], dtype=float) for t in TYPES}

    labelled = {p for p in set(proj) if y[proj == p].sum() > 0}
    keep = np.array([p in labelled for p in proj])
    out = {"seed": SEED, "n_bootstrap": N_BOOT,
           "primary_population": {
               "projects": len(labelled), "commits": int(keep.sum()),
               "excluded_projects": sorted(set(proj) - labelled),
               "excluded_commits": int((~keep).sum()),
               "excluded_share_of_violations": float(nviol[~keep].sum() / nviol.sum())}}

    P, C, Y = proj[keep], churn[keep], y[keep]
    V = nviol[keep]
    print(f"primary population: {len(labelled)} projects, {keep.sum():,} commits, "
          f"base rate {Y.mean():.2%}")
    print(f"excluded: {sorted(set(proj) - labelled)}, "
          f"{(~keep).sum():,} commits carrying "
          f"{nviol[~keep].sum() / nviol.sum():.1%} of all violations\n")

    # ---- policies, corrected population ----
    print("== policies on the primary population ==")
    pol = {"any violation": score(V > 0, Y)}
    for s in SEVERITIES:
        pol[f"severity {s}"] = score(sev[s][keep] > 0, Y)
    for t in TYPES:
        pol[f"type {t}"] = score(typ[t][keep] > 0, Y)
    for k, v in pol.items():
        print(f"   {k:22} prec {v['precision']:>6.2%}  rec {v['recall']:>6.2%}  "
              f"{v['alerts_per_1000']:>6.1f}/1k  lift {v['lift']:.2f}")
    out["policies"] = pol
    best = max(pol, key=lambda k: pol[k]["lift"])
    print(f"\n   best policy by lift: {best} at {pol[best]['lift']:.2f}")
    out["best_policy"] = best

    # ---- the question that matters: what does the flag add given size? ----
    print("\n== conditioning on commit size ==")
    q = np.quantile(C, [0.2, 0.4, 0.6, 0.8])
    strata = np.digitize(C, q)
    pooled = score(V > 0, Y)
    rows_ = []
    for s in range(5):
        m = strata == s
        e = score(V[m] > 0, Y[m])
        e["quintile"] = s + 1
        e["churn_range"] = [float(C[m].min()), float(C[m].max())]
        rows_.append(e)
        print(f"   quintile {s + 1}: n {e['n']:>6,}  churn {C[m].min():>6.0f}-{C[m].max():>8.0f}  "
              f"base {e['base_rate']:>6.2%}  prec {e['precision']:>6.2%}  lift {e['lift']:.2f}")
    # Review round two showed the unweighted mean of stratum lifts is a fragile estimator: lifts in
    # low-base-rate strata blow up, and the answer moves with the number of strata. The stable
    # quantity is the standardised one, the ratio of positives actually caught among flagged commits
    # to the number expected if the flag carried no information within its stratum. That is a
    # Mantel-Haenszel style common-effect estimate and it barely moves with the bin count. Both are
    # reported, at three resolutions, and the paper quotes the standardised one.
    lifts = [x["lift"] for x in rows_]
    mean_within = float(np.mean(lifts))

    def standardised(nbins):
        edges = np.quantile(C, np.linspace(0, 1, nbins + 1)[1:-1])
        st = np.digitize(C, edges)
        obs = exp = 0.0
        for s in range(nbins):
            m = st == s
            if m.sum() == 0 or Y[m].sum() == 0:
                continue
            f = V[m] > 0
            obs += float((f & Y[m]).sum())
            exp += float(f.sum() * Y[m].mean())
        return (obs / exp) if exp else float("nan")

    print(f"\n   pooled lift {pooled['lift']:.3f}")
    print(f"   unweighted mean of stratum lifts (5 bins): {mean_within:.3f}")
    share_unw = 1 - (mean_within - 1) / (pooled["lift"] - 1)
    print(f"      -> share attributable to size: {share_unw:.0%}")
    std_by_bins = {}
    for nb in (5, 10, 20, 50):
        L = standardised(nb)
        std_by_bins[nb] = L
        sh = 1 - (L - 1) / (pooled["lift"] - 1)
        print(f"   standardised lift at {nb:>2} bins: {L:.3f}   "
              f"-> share attributable to size: {sh:.0%}")
    L5 = std_by_bins[5]
    share_std = 1 - (L5 - 1) / (pooled["lift"] - 1)

    boot = np.empty(N_BOOT)
    n = len(Y)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, n)
        ls = []
        for s in range(5):
            m = strata[idx] == s
            if m.sum() < 30 or Y[idx][m].sum() == 0:
                continue
            e = score(V[idx][m] > 0, Y[idx][m])
            if e["lift"]:
                ls.append(e["lift"])
        boot[i] = np.mean(ls) if ls else np.nan
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    share_lo = 1 - (hi - 1) / (pooled["lift"] - 1)
    share_hi = 1 - (lo - 1) / (pooled["lift"] - 1)
    print(f"   mean within-stratum lift 95% CI [{lo:.2f}, {hi:.2f}]")
    print(f"   implied share attributable to size: "
          f"{share_unw:.0%} [{share_lo:.0%}, {share_hi:.0%}]")
    out["size_conditional"] = {
        "pooled": pooled, "strata": rows_,
        "mean_within_lift": mean_within,
        "mean_within_ci": [float(lo), float(hi)],
        "share_unweighted": float(share_unw),
        "share_ci": [float(share_lo), float(share_hi)],
        "standardised_lift_by_bins": {str(k): float(v) for k, v in std_by_bins.items()},
        "standardised_lift": float(L5),
        "share_standardised": float(share_std),
        "share_standardised_by_bins": {
            str(k): float(1 - (v - 1) / (pooled["lift"] - 1)) for k, v in std_by_bins.items()},
    }

    # ---- budget curves in both units ----
    print("\n== budget curve, denominated in COMMITS reviewed ==")
    ones = np.ones(len(Y))
    curves_commits = []
    for b in BUDGETS:
        k = len(Y) * b / 1000
        rv = recall_at_cost(V, Y, ones, k)
        rc = recall_at_cost(C, Y, ones, k)
        rr = recall_at_cost(rng.random(len(Y)), Y, ones, k)
        curves_commits.append({"budget_per_1000": b, "violations": rv, "churn": rc, "random": rr})
        print(f"   {b:>4}/1k  violations {rv:>6.1%}  churn {rc:>6.1%}  random {rr:>6.1%}")
    out["budget_commits"] = curves_commits

    print("\n== budget curve, denominated in CHANGED LINES reviewed ==")
    # When cost is proportional to size, ranking by raw score is the wrong policy and the
    # effort-aware literature says so: what matters is yield per line. So the candidates here are
    # densities, plus the two floors that expose whether any of it is doing work. "smallest first"
    # is included deliberately: it is the degenerate policy that maximises commits reviewed per line
    # and it beats a great deal of published machinery.
    lines = np.maximum(C, 1.0)
    total_lines = C.sum()
    policies_l = {
        "violations per line": V / lines,
        "violations, raw rank": V,
        "churn, raw rank": C,
        "smallest commits first": -C,
        "random": rng.random(len(Y)),
    }
    curves_lines = []
    print(f"   {'budget':>8} " + " ".join(f"{k:>22}" for k in policies_l))
    for b in BUDGETS:
        lim = total_lines * b / 1000
        row = {"budget_per_1000_lines": b}
        cells = []
        for name, sc in policies_l.items():
            r_ = recall_at_cost(sc, Y, C, lim)
            row[name] = r_
            cells.append(f"{r_:>21.1%} ")
        curves_lines.append(row)
        print(f"   {b:>7}  " + " ".join(cells))
    out["budget_lines"] = curves_lines

    best_l = {}
    for row in curves_lines:
        cand = {k: v for k, v in row.items() if k != "budget_per_1000_lines"}
        best_l[row["budget_per_1000_lines"]] = max(cand, key=cand.get)
    print("\n   best policy per line budget:", best_l)
    out["best_per_line_budget"] = best_l
    beats_density = [b for b, w in best_l.items() if w == "violations per line"]
    print(f"   budgets where violations per line is the best policy: {beats_density}")
    out["density_wins_at"] = beats_density

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
