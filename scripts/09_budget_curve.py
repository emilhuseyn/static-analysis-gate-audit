# The deliverable: at a review budget a team actually has, which gate catches the most faults?
#
# Every policy is reduced to the same currency - alerts per thousand commits - so they can be laid
# side by side. Four candidates, and the two floors that any of them must beat to be worth deploying:
#
#   violations   rank commits by how many violations they introduce
#   critical     rank by count of BLOCKER or CRITICAL violations only
#   churn        rank by lines added plus removed. No static analysis at all. This is the floor the
#                just-in-time defect prediction literature has known about for years and the static
#                analysis literature does not report against.
#   random       rank at random, seeded. The other floor.
#
# Ties are broken deterministically so the curve is reproducible, and a ranking that cannot separate
# commits is not silently credited for it: within a tie the expected recall is used.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\09_budget_curve.py
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "budget_curve.json")

SEED = 20260808
BUDGETS = [5, 10, 25, 50, 100, 200, 300, 500]  # alerts per 1000 commits


def load(cur):
    rows = cur.execute("""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
            GROUP BY g.COMMIT_HASH
        ),
        viol AS (
            SELECT a.REVISION h, COUNT(*) k,
                   SUM(CASE WHEN i.SEVERITY IN ('BLOCKER','CRITICAL') THEN 1 ELSE 0 END) crit
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        ),
        churn AS (
            SELECT COMMIT_HASH h, SUM(COALESCE(LINES_ADDED,0) + COALESCE(LINES_REMOVED,0)) c
            FROM GIT_COMMITS_CHANGES GROUP BY COMMIT_HASH
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT COALESCE(v.k,0) nviol, COALESCE(v.crit,0) ncrit,
               COALESCE(ch.c,0) churn,
               CASE WHEN p.h IS NOT NULL THEN 1 ELSE 0 END y
        FROM gate
        LEFT JOIN viol v ON v.h = gate.h
        LEFT JOIN churn ch ON ch.h = gate.h
        LEFT JOIN pos p ON p.h = gate.h
    """).fetchall()
    return (np.array([r["nviol"] for r in rows], dtype=float),
            np.array([r["ncrit"] for r in rows], dtype=float),
            np.array([r["churn"] for r in rows], dtype=float),
            np.array([r["y"] for r in rows], dtype=bool))


def recall_at_budget(scores, y, k, rng):
    """Recall when the top k commits by score are reviewed.

    Ties are resolved by expectation rather than by whatever order the rows happen to be in, so a
    score that cannot distinguish commits gets no free credit from the sort.
    """
    n = len(y)
    if k <= 0:
        return 0.0
    if k >= n:
        return 1.0
    order = np.argsort(-scores, kind="stable")
    s_sorted = scores[order]
    cut = s_sorted[k - 1]
    strictly_above = scores > cut
    n_above = int(strictly_above.sum())
    tp_above = int(y[strictly_above].sum())
    tied = scores == cut
    n_tied = int(tied.sum())
    tp_tied = int(y[tied].sum())
    remaining = k - n_above
    expected = tp_above + (tp_tied * remaining / n_tied if n_tied else 0)
    return expected / int(y.sum())


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    nviol, ncrit, churn, y = load(con.cursor())
    con.close()
    rng = np.random.default_rng(SEED)
    n, pos = len(y), int(y.sum())
    print(f"gateable commits {n:,}   fault-inducing {pos:,}   base rate {pos / n:.2%}")
    print(f"commits with churn recorded: {(churn > 0).sum():,}\n")

    policies = {
        "violations": nviol,
        "critical only": ncrit,
        "churn (no static analysis)": churn,
        "random": rng.random(n),
    }

    header = "budget/1k  " + "  ".join(f"{k:>26}" for k in policies)
    print(header)
    print("-" * len(header))
    table = []
    for b in BUDGETS:
        k = int(round(n * b / 1000))
        row = {"budget_per_1000": b, "reviewed": k}
        cells = []
        for name, sc in policies.items():
            r = recall_at_budget(sc, y, k, rng)
            row[name] = r
            cells.append(f"{r:>25.1%} ")
        table.append(row)
        print(f"{b:>7}    " + " ".join(cells))

    print("\nwhat that means:")
    for b in (25, 50, 100):
        r = next(x for x in table if x["budget_per_1000"] == b)
        best = max(policies, key=lambda k2: r[k2])
        print(f"   at {b:>3} alerts per 1,000 commits the best policy is "
              f"'{best}' at {r[best]:.1%} recall; "
              f"churn alone gives {r['churn (no static analysis)']:.1%}")

    beaten = [x["budget_per_1000"] for x in table
              if x["churn (no static analysis)"] >= x["violations"]]
    print(f"\nbudgets at which plain churn matches or beats the violation ranking: {beaten}")

    out = {"seed": SEED, "commits": n, "positives": pos, "base_rate": pos / n,
           "commits_with_churn": int((churn > 0).sum()),
           "budgets": table, "churn_beats_violations_at": beaten}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
