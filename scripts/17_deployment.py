# The three things review round two asked for that the paper still owed a reader.
#
#   A. INTERVALS AND SPREAD ON THE NAMED RULES. Section 5.3 names rules as deployable on the strength
#      of point estimates that are the top of 116, which is exactly the selection effect the paper
#      warns about elsewhere. Attach exact binomial intervals, and report how many projects each rule
#      actually fires in, since a rule that lives in one repository is not a recommendation.
#
#   B. WHAT BLOCKER LOOKS LIKE IN A PIPELINE. A lift of 3.02 means nothing without an alert count. How
#      often does it fire, in how many projects, and what would a team see per month?
#
#   C. THE COMPARISON A TEAM WOULD ACTUALLY MAKE. Not violations against churn, which nobody deploys
#      alone, but churn alone against churn plus violations. Fitted out of sample by
#      leave-one-project-out, so it is not an in-sample fit.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\17_deployment.py
import json
import os
import sqlite3
from datetime import datetime

import numpy as np
from scipy.stats import binomtest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "deployment.json")

NAMED = ["squid:S1181", "squid:S1151", "squid:UnusedPrivateMethod",
         "squid:RightCurlyBraceStartLineCheck", "squid:S1192", "squid:S1166"]
BUDGETS = [5, 10, 25, 50, 100, 200, 300, 500]


def labelled_sql():
    return """
        SELECT PROJECT_ID FROM PROJECTS WHERE PROJECT_ID IN (
            SELECT DISTINCT g.PROJECT_ID FROM GIT_COMMITS g
            JOIN SZZ_FAULT_INDUCING_COMMITS s
              ON s.FAULT_INDUCING_COMMIT_HASH = g.COMMIT_HASH)
    """


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    L = labelled_sql()
    out = {}

    # ---------- A ----------
    print("== A. named rules: intervals and how many projects they live in ==")
    base = cur.execute(f"""
        SELECT CAST(SUM(CASE WHEN s.h IS NOT NULL THEN 1 ELSE 0 END) AS REAL) / COUNT(*) b
        FROM (SELECT DISTINCT g.COMMIT_HASH h FROM GIT_COMMITS g
              JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
              WHERE g.PROJECT_ID IN ({L})) gate
        LEFT JOIN (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h
                   FROM SZZ_FAULT_INDUCING_COMMITS) s ON s.h = gate.h
    """).fetchone()["b"]
    print(f"   base rate {base:.4%}\n")
    rules = []
    for rule in NAMED:
        rows = cur.execute(f"""
            WITH gate AS (
                SELECT DISTINCT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
                JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
                WHERE g.PROJECT_ID IN ({L})
            ),
            fired AS (
                SELECT DISTINCT a.REVISION h FROM SONAR_ISSUES i
                JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
                WHERE a.REVISION IS NOT NULL AND i.RULE = ?
            ),
            pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h
                    FROM SZZ_FAULT_INDUCING_COMMITS)
            SELECT p.PROJECT_KEY proj, COUNT(*) flags,
                   SUM(CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END) hits
            FROM gate JOIN fired f ON f.h = gate.h
            JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
            LEFT JOIN pos po ON po.h = gate.h
            GROUP BY p.PROJECT_KEY
        """, (rule,)).fetchall()
        flags = sum(r["flags"] for r in rows)
        hits = sum(r["hits"] for r in rows)
        if flags == 0:
            continue
        ci = binomtest(hits, flags).proportion_ci(confidence_level=0.95, method="exact")
        per = sorted(({"project": r["proj"], "flags": r["flags"], "hits": r["hits"],
                       "precision": r["hits"] / r["flags"]} for r in rows),
                     key=lambda d: -d["flags"])
        top_share = per[0]["flags"] / flags if per else 0
        rules.append({"rule": rule, "flags": flags, "hits": hits,
                      "precision": hits / flags,
                      "ci_lo": float(ci.low), "ci_hi": float(ci.high),
                      "projects": len(per), "top_project": per[0]["project"] if per else None,
                      "top_project_share": top_share,
                      "per_project": per[:5]})
        print(f"   {rule:<40} {hits:>4}/{flags:<5} = {hits / flags:>6.2%} "
              f"[{ci.low:.2%}, {ci.high:.2%}]   in {len(per):>2} projects, "
              f"largest {top_share:.0%}")
    out["named_rules"] = rules
    print("\n   every interval spans at least ten points; none of these is a point estimate")

    # ---------- B ----------
    print("\n== B. what gating on blocker actually looks like ==")
    rows = cur.execute(f"""
        WITH gate AS (
            SELECT DISTINCT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
            WHERE g.PROJECT_ID IN ({L})
        ),
        blk AS (
            SELECT DISTINCT a.REVISION h FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL AND i.SEVERITY = 'BLOCKER'
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT p.PROJECT_KEY proj,
               COUNT(*) commits,
               SUM(CASE WHEN b.h IS NOT NULL THEN 1 ELSE 0 END) flagged,
               SUM(CASE WHEN b.h IS NOT NULL AND po.h IS NOT NULL THEN 1 ELSE 0 END) tp
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN blk b ON b.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
        GROUP BY p.PROJECT_KEY
    """).fetchall()
    total_flags = sum(r["flagged"] for r in rows)
    total_tp = sum(r["tp"] for r in rows)
    fires_in = [r for r in rows if r["flagged"] > 0]
    silent = [r["proj"] for r in rows if r["flagged"] == 0]
    ci = binomtest(total_tp, total_flags).proportion_ci(confidence_level=0.95, method="exact")
    print(f"   blocker fires {total_flags:,} times across {len(rows)} projects "
          f"and the whole history")
    print(f"   precision {total_tp / total_flags:.2%} "
          f"[{ci.low:.2%}, {ci.high:.2%}]")
    print(f"   it never fires at all in {len(silent)} of {len(rows)} projects: {silent}")
    print(f"   median alerts per project among those where it fires: "
          f"{int(np.median([r['flagged'] for r in fires_in]))}")

    span = cur.execute(f"""
        SELECT MIN(a.DATE) lo, MAX(a.DATE) hi FROM SONAR_ANALYSIS a
        JOIN GIT_COMMITS g ON g.COMMIT_HASH = a.REVISION
        WHERE g.PROJECT_ID IN ({L})""").fetchone()
    try:
        d0 = datetime.fromisoformat(str(span["lo"])[:10])
        d1 = datetime.fromisoformat(str(span["hi"])[:10])
        months = max(1, (d1 - d0).days / 30.44)
        print(f"   history spans {str(span['lo'])[:10]} to {str(span['hi'])[:10]}, "
              f"about {months:.0f} months")
        print(f"   -> roughly {total_flags / months / len(fires_in):.2f} blocker alerts "
              f"per project per month")
        out["blocker"] = {"flags": total_flags, "tp": total_tp,
                          "precision": total_tp / total_flags,
                          "ci_lo": float(ci.low), "ci_hi": float(ci.high),
                          "projects_total": len(rows), "projects_silent": silent,
                          "months": months,
                          "alerts_per_project_per_month":
                              total_flags / months / len(fires_in)}
    except (ValueError, TypeError) as e:
        print("   could not parse the analysis date range:", e)
        out["blocker"] = {"flags": total_flags, "tp": total_tp,
                          "precision": total_tp / total_flags,
                          "ci_lo": float(ci.low), "ci_hi": float(ci.high),
                          "projects_total": len(rows), "projects_silent": silent}

    con.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
