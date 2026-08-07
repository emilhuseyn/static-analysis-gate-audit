# What the simplest real gate is worth, before any model exists.
#
# Every team that turns on a static-analysis gate starts from one policy: block, or flag for review,
# any commit that introduces at least one violation. Some tighten it to a severity. Nobody in the
# fault-prediction literature reports what that policy costs and buys, because the literature reports
# AUC. This measures it directly, at the real base rate, with no model and no rebalancing.
#
# It also fixes the ceiling every later model must beat: a gate keyed on introduced violations cannot
# catch a fault-inducing commit that introduced none.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\06_trivial_gate.py
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "trivial_gate.json")

SEVERITIES = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
TYPES = ["BUG", "VULNERABILITY", "CODE_SMELL"]


def evaluate(cur, where_sql, params, label):
    """Flag a gateable commit if it introduces at least one issue matching where_sql."""
    row = cur.execute(f"""
        WITH gate AS (
            SELECT DISTINCT g.COMMIT_HASH h FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        ),
        flagged AS (
            SELECT DISTINCT a.REVISION h
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL {where_sql}
        ),
        pos AS (
            SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS
        )
        SELECT
          COUNT(*) n,
          SUM(CASE WHEN p.h IS NOT NULL THEN 1 ELSE 0 END) positives,
          SUM(CASE WHEN f.h IS NOT NULL THEN 1 ELSE 0 END) flagged,
          SUM(CASE WHEN f.h IS NOT NULL AND p.h IS NOT NULL THEN 1 ELSE 0 END) tp
        FROM gate
        LEFT JOIN flagged f ON f.h = gate.h
        LEFT JOIN pos p ON p.h = gate.h
    """, params).fetchone()

    n, pos, fl, tp = row["n"], row["positives"], row["flagged"], row["tp"]
    fp = fl - tp
    prec = tp / fl if fl else 0.0
    rec = tp / pos if pos else 0.0
    base = pos / n if n else 0.0
    # net benefit at the threshold this policy implicitly sets, in the decision-curve sense:
    # treating one missed fault as worth 1 and one wasted review as worth p/(1-p) at that threshold.
    # Here the policy has no tunable threshold, so report the plain review cost instead.
    return {"policy": label, "commits": n, "positives": pos, "base_rate": base,
            "flagged": fl, "true_positives": tp, "false_positives": fp,
            "precision": prec, "recall": rec,
            "alerts_per_1000_commits": 1000 * fl / n if n else 0,
            "lift_over_base": (prec / base) if base else 0}


def show(r):
    print(f"  {r['policy']:34} flags {r['flagged']:>7,}  "
          f"prec {r['precision']:>6.2%}  rec {r['recall']:>6.2%}  "
          f"{r['alerts_per_1000_commits']:>6.0f}/1k  lift {r['lift_over_base']:.2f}x")


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    results = []

    print("== the ceiling: can a violation-keyed gate even see the faults? ==")
    ceiling = cur.execute("""
        WITH gate AS (
            SELECT DISTINCT g.COMMIT_HASH h FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        ),
        intro AS (
            SELECT DISTINCT a.REVISION h FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT COUNT(*) faults,
               SUM(CASE WHEN i.h IS NOT NULL THEN 1 ELSE 0 END) visible
        FROM gate JOIN pos p ON p.h = gate.h
        LEFT JOIN intro i ON i.h = gate.h
    """).fetchone()
    print(f"  fault-inducing gateable commits         {ceiling['faults']:>8,}")
    print(f"  of those, introducing >=1 violation     {ceiling['visible']:>8,}"
          f"   ({ceiling['visible'] / ceiling['faults']:.1%})")
    print(f"  MAXIMUM RECALL of any such gate         {ceiling['visible'] / ceiling['faults']:.1%}")

    print("\n== flag any commit introducing at least one violation ==")
    r = evaluate(cur, "", (), "any violation")
    show(r)
    results.append(r)
    print(f"  (base rate {r['base_rate']:.2%}, so a coin weighted to the base rate "
          f"would reach {r['base_rate']:.2%} precision)")

    print("\n== tightened by severity ==")
    for sev in SEVERITIES:
        r = evaluate(cur, "AND i.SEVERITY = ?", (sev,), f"severity = {sev}")
        show(r)
        results.append(r)

    print("\n== tightened by issue type ==")
    for t in TYPES:
        r = evaluate(cur, "AND i.TYPE = ?", (t,), f"type = {t}")
        show(r)
        results.append(r)

    print("\n== the tightest sensible rule: blocker bugs only ==")
    r = evaluate(cur, "AND i.TYPE = 'BUG' AND i.SEVERITY IN ('BLOCKER','CRITICAL')", (),
                 "BUG at blocker or critical")
    show(r)
    results.append(r)

    con.close()
    out = {"ceiling": {"fault_inducing": ceiling["faults"], "visible": ceiling["visible"],
                       "invisible": ceiling["faults"] - ceiling["visible"],
                       "max_recall": ceiling["visible"] / ceiling["faults"]},
           "policies": results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
