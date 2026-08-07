# The comparison a team would actually make.
#
# Sections 5 to 7 pit violations against churn. No team deploys either alone; the real question is
# whether static analysis adds anything ON TOP of knowing how large the change is. This fits three
# rankings and scores them at the same budgets, in both cost units:
#
#   churn only            log(1 + changed lines)
#   violations only       log(1 + violations introduced)
#   both                  a logistic model on the two
#
# Fitted LEAVE-ONE-PROJECT-OUT, so every commit is scored by a model that never saw its repository.
# An in-sample fit would flatter the combined model for free.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\18_combined.py
import json
import os
import sqlite3

import numpy as np
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "combined.json")

SEED = 20260808
BUDGETS = [5, 10, 25, 50, 100, 200, 300, 500]


def load(cur):
    return cur.execute("""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH GROUP BY g.COMMIT_HASH
        ),
        viol AS (
            SELECT a.REVISION h, COUNT(*) k FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        ),
        churn AS (
            SELECT COMMIT_HASH h, SUM(COALESCE(LINES_ADDED,0)+COALESCE(LINES_REMOVED,0)) c
            FROM GIT_COMMITS_CHANGES GROUP BY COMMIT_HASH
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT p.PROJECT_KEY proj, COALESCE(v.k,0) nviol, COALESCE(ch.c,0) churn,
               CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END y
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN viol v ON v.h = gate.h
        LEFT JOIN churn ch ON ch.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
    """).fetchall()


def recall_at_cost(scores, y, cost, budget, rng):
    """Ties resolved by expectation, as everywhere else in this paper."""
    total_pos = int(y.sum())
    if budget <= 0 or total_pos == 0:
        return 0.0
    order = np.argsort(-scores, kind="stable")
    spent = np.cumsum(cost[order])
    k = int(np.searchsorted(spent, budget, side="right"))
    if k >= len(y):
        return 1.0
    cut = scores[order][k]
    above = scores > cut
    caught = int(y[above].sum())
    tied = scores == cut
    if not tied.any():
        return caught / total_pos
    remaining = budget - float(cost[above].sum())
    tied_cost = float(cost[tied].sum())
    share = 0.0 if tied_cost <= 0 else max(0.0, min(1.0, remaining / tied_cost))
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
    labelled = {p for p in set(proj) if y[proj == p].sum() > 0}
    keep = np.array([p in labelled for p in proj])
    P, Y = proj[keep], y[keep]
    lc = np.log1p(churn[keep])
    lv = np.log1p(nviol[keep])
    cost_commit = np.ones(len(Y))
    cost_line = churn[keep]

    print(f"population: {len(labelled)} projects, {len(Y):,} commits, base {Y.mean():.2%}")
    print("fitting leave-one-project-out ...")

    feats = {"churn only": np.column_stack([lc]),
             "violations only": np.column_stack([lv]),
             "both": np.column_stack([lc, lv])}
    scores = {k: np.zeros(len(Y)) for k in feats}
    coefs = []
    for p in sorted(labelled):
        te = P == p
        tr = ~te
        if Y[tr].sum() == 0 or Y[tr].all():
            continue
        for name, X in feats.items():
            m = LogisticRegression(max_iter=2000, solver="lbfgs")
            m.fit(X[tr], Y[tr])
            scores[name][te] = m.predict_proba(X[te])[:, 1]
            if name == "both":
                coefs.append({"held_out": p, "coef_log_churn": float(m.coef_[0][0]),
                              "coef_log_violations": float(m.coef_[0][1])})

    cv = np.array([c["coef_log_violations"] for c in coefs])
    cc = np.array([c["coef_log_churn"] for c in coefs])
    print(f"\n   log-churn coefficient      median {np.median(cc):+.3f}  "
          f"({(cc > 0).sum()}/{len(cc)} folds positive)")
    print(f"   log-violations coefficient median {np.median(cv):+.3f}  "
          f"({(cv > 0).sum()}/{len(cv)} folds positive)")

    out = {"seed": SEED, "projects": len(labelled), "commits": int(len(Y)),
           "base_rate": float(Y.mean()), "fold_coefficients": coefs,
           "median_coef_log_churn": float(np.median(cc)),
           "median_coef_log_violations": float(np.median(cv)),
           "folds_with_positive_violation_coef": int((cv > 0).sum()), "folds": len(cv)}

    for unit, cost, total in (("commits reviewed", cost_commit, float(len(Y))),
                              ("changed lines reviewed", cost_line, float(cost_line.sum()))):
        print(f"\n== budget in {unit} ==")
        print(f"   {'budget':>7} {'churn only':>12} {'violations':>12} {'both':>10} {'gain':>8}")
        rows = []
        for b in BUDGETS:
            lim = total * b / 1000
            a = recall_at_cost(scores["churn only"], Y, cost, lim, rng)
            v = recall_at_cost(scores["violations only"], Y, cost, lim, rng)
            t = recall_at_cost(scores["both"], Y, cost, lim, rng)
            rows.append({"budget_per_1000": b, "churn_only": a,
                         "violations_only": v, "both": t, "gain_over_churn": t - a})
            print(f"   {b:>7} {a:>11.1%} {v:>11.1%} {t:>9.1%} {t - a:>+7.1%}")
        out[f"budget_{unit.split()[0]}"] = rows
        gains = [x["gain_over_churn"] for x in rows]
        print(f"   adding violations to churn is worth between "
              f"{min(gains):+.1%} and {max(gains):+.1%} recall")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
