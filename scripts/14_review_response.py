# Check the review panel's empirical claims against the data, before conceding or rejecting any of
# them. Every number the reviewers computed is recomputed here from scratch.
#
# The claims under test:
#   A. the three projects with no SZZ labels supply half the violation mass, and excluding them
#      REVERSES the severity finding, BLOCKER overtaking INFO
#   B. on the labelled population, churn no longer beats the violation ranking at tight budgets
#   C. within churn strata the violation flag adds far less than the pooled lift suggests, so most of
#      the apparent signal is commit size
#   D. analysis coverage varies enormously by project, so "introduced by" spans a window of commits
#   E. the gateable population is selected on the outcome: analysed commits are more fault-prone than
#      unanalysed ones, which the paper never reports
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\14_review_response.py
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "review_response.json")

SEED = 20260808
BUDGETS = [5, 10, 25, 50, 100, 200, 300, 500]


def rows(cur):
    return cur.execute("""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
            GROUP BY g.COMMIT_HASH
        ),
        viol AS (
            SELECT a.REVISION h, COUNT(*) k,
                   SUM(CASE WHEN i.SEVERITY IN ('BLOCKER','CRITICAL') THEN 1 ELSE 0 END) crit,
                   SUM(CASE WHEN i.SEVERITY = 'BLOCKER' THEN 1 ELSE 0 END) blocker,
                   SUM(CASE WHEN i.SEVERITY = 'INFO' THEN 1 ELSE 0 END) info
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        ),
        churn AS (
            SELECT COMMIT_HASH h, SUM(COALESCE(LINES_ADDED,0)+COALESCE(LINES_REMOVED,0)) c
            FROM GIT_COMMITS_CHANGES GROUP BY COMMIT_HASH
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT p.PROJECT_KEY proj, COALESCE(v.k,0) nviol, COALESCE(v.crit,0) ncrit,
               COALESCE(v.blocker,0) nblock, COALESCE(v.info,0) ninfo,
               COALESCE(ch.c,0) churn,
               CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END y
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN viol v ON v.h = gate.h
        LEFT JOIN churn ch ON ch.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
    """).fetchall()


def prec_recall(flag, y):
    fl = int(flag.sum())
    tp = int((flag & y).sum())
    pos = int(y.sum())
    n = len(y)
    base = pos / n if n else 0
    return {"flagged": fl, "tp": tp, "precision": tp / fl if fl else 0.0,
            "recall": tp / pos if pos else 0.0,
            "alerts_per_1000": 1000 * fl / n if n else 0.0,
            "base_rate": base, "lift": ((tp / fl) / base) if fl and base else 0.0}


def recall_at(scores, y, k):
    n = len(y)
    if k <= 0:
        return 0.0
    if k >= n:
        return 1.0
    s = np.sort(scores)[::-1]
    cut = s[k - 1]
    above = scores > cut
    tied = scores == cut
    rem = k - int(above.sum())
    exp = int(y[above].sum()) + (int(y[tied].sum()) * rem / int(tied.sum()) if tied.sum() else 0)
    return exp / int(y.sum())


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    r = rows(cur)

    proj = np.array([x["proj"] for x in r])
    nviol = np.array([x["nviol"] for x in r], dtype=float)
    ncrit = np.array([x["ncrit"] for x in r], dtype=float)
    nblock = np.array([x["nblock"] for x in r], dtype=float)
    ninfo = np.array([x["ninfo"] for x in r], dtype=float)
    churn = np.array([x["churn"] for x in r], dtype=float)
    y = np.array([x["y"] for x in r], dtype=bool)

    labelled_projects = {p for p in set(proj) if y[proj == p].sum() > 0}
    keep = np.array([p in labelled_projects for p in proj])
    out = {"seed": SEED}

    # ---------- A ----------
    print("== A. the three unlabelled projects ==")
    dropped = sorted(set(proj) - labelled_projects)
    print("   projects with no positive label:", dropped)
    share_commits = (~keep).sum() / len(proj)
    share_viol = nviol[~keep].sum() / nviol.sum()
    share_crit = ncrit[~keep].sum() / ncrit.sum()
    print(f"   they are {share_commits:.1%} of gateable commits")
    print(f"   they supply {share_viol:.1%} of all introduced violations")
    print(f"   and {share_crit:.1%} of the BLOCKER or CRITICAL mass")
    out["unlabelled"] = {"projects": dropped, "share_commits": share_commits,
                         "share_violations": share_viol, "share_critical": share_crit}

    print("\n   severity policies, all 31 projects vs the 28 labelled ones:")
    sev_cols = {"BLOCKER": nblock, "INFO": ninfo, "CRITICAL_OR_BLOCKER": ncrit}
    sev = {}
    for name, col in sev_cols.items():
        a = prec_recall(col > 0, y)
        b = prec_recall(col[keep] > 0, y[keep])
        sev[name] = {"all31": a, "labelled28": b}
        print(f"   {name:20} all31 prec {a['precision']:>6.2%} lift {a['lift']:.2f}   "
              f"| 28 prec {b['precision']:>6.2%} lift {b['lift']:.2f}")
    any_all = prec_recall(nviol > 0, y)
    any_28 = prec_recall(nviol[keep] > 0, y[keep])
    print(f"   {'any violation':20} all31 prec {any_all['precision']:>6.2%} "
          f"lift {any_all['lift']:.2f}   | 28 prec {any_28['precision']:>6.2%} "
          f"lift {any_28['lift']:.2f}")
    sev["any"] = {"all31": any_all, "labelled28": any_28}
    reversed_ = sev["BLOCKER"]["labelled28"]["precision"] > sev["INFO"]["labelled28"]["precision"]
    print(f"\n   DOES THE SEVERITY ORDERING REVERSE ON THE 28? {reversed_}")
    out["severity"] = sev
    out["severity_reverses_on_labelled"] = bool(reversed_)

    # ---------- B ----------
    print("\n== B. budget curve on the labelled population ==")
    yk, nk, ck = y[keep], nviol[keep], churn[keep]
    n = len(yk)
    print(f"   {'budget':>8} {'violations':>12} {'churn':>10} {'winner':>12}")
    budget_rows = []
    for b in BUDGETS:
        k = int(round(n * b / 1000))
        rv = recall_at(nk, yk, k)
        rc = recall_at(ck, yk, k)
        w = "violations" if rv > rc else ("churn" if rc > rv else "tie")
        budget_rows.append({"budget_per_1000": b, "violations": rv, "churn": rc, "winner": w})
        print(f"   {b:>8} {rv:>11.1%} {rc:>9.1%} {w:>12}")
    out["budget_labelled"] = budget_rows

    # ---------- C ----------
    print("\n== C. does the violation flag survive conditioning on commit size? ==")
    q = np.quantile(ck, [0.2, 0.4, 0.6, 0.8])
    strata = np.digitize(ck, q)
    pooled = prec_recall(nk > 0, yk)
    print(f"   pooled on the 28: precision {pooled['precision']:.2%}, lift {pooled['lift']:.2f}")
    strat = []
    for s in range(5):
        m = strata == s
        if m.sum() < 50 or yk[m].sum() == 0:
            continue
        e = prec_recall(nk[m] > 0, yk[m])
        strat.append({"quintile": s + 1, "n": int(m.sum()), **e})
        print(f"   churn quintile {s + 1}: n {m.sum():>6,}  base {e['base_rate']:>6.2%}  "
              f"prec {e['precision']:>6.2%}  lift {e['lift']:.2f}")
    if strat:
        lifts = [x["lift"] for x in strat]
        print(f"   within-stratum lift: min {min(lifts):.2f}, max {max(lifts):.2f}, "
              f"mean {float(np.mean(lifts)):.2f}   against pooled {pooled['lift']:.2f}")
        out["churn_strata"] = {"pooled": pooled, "strata": strat,
                               "mean_within_lift": float(np.mean(lifts))}

    # ---------- D ----------
    print("\n== D. analysis coverage per project ==")
    cov = []
    for p in sorted(set(proj)):
        total = cur.execute("""SELECT COUNT(DISTINCT g.COMMIT_HASH) n FROM GIT_COMMITS g
            JOIN PROJECTS pr ON pr.PROJECT_ID = g.PROJECT_ID WHERE pr.PROJECT_KEY = ?""",
                            (p,)).fetchone()["n"]
        an = int((proj == p).sum())
        cov.append({"project": p, "commits": total, "analysed": an,
                    "coverage": an / total if total else 0})
    cov.sort(key=lambda x: x["coverage"])
    for c in cov[:3] + cov[-3:]:
        print(f"   {c['project'][:26]:26} {c['analysed']:>6,}/{c['commits']:>6,} "
              f"= {c['coverage']:>6.1%}")
    cvals = [c["coverage"] for c in cov]
    print(f"   coverage ranges {min(cvals):.1%} to {max(cvals):.1%}, "
          f"median {float(np.median(cvals)):.1%}")
    out["coverage"] = {"per_project": cov, "min": min(cvals), "max": max(cvals),
                       "median": float(np.median(cvals))}

    # ---------- E ----------
    print("\n== E. is the gateable population selected on the outcome? ==")
    e = cur.execute("""
        WITH an AS (SELECT DISTINCT REVISION h FROM SONAR_ANALYSIS WHERE REVISION IS NOT NULL),
             pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT
          SUM(CASE WHEN an.h IS NULL THEN 1 ELSE 0 END) not_analysed,
          SUM(CASE WHEN an.h IS NULL AND p.h IS NOT NULL THEN 1 ELSE 0 END) not_analysed_pos,
          SUM(CASE WHEN an.h IS NOT NULL THEN 1 ELSE 0 END) analysed,
          SUM(CASE WHEN an.h IS NOT NULL AND p.h IS NOT NULL THEN 1 ELSE 0 END) analysed_pos
        FROM GIT_COMMITS g
        LEFT JOIN an ON an.h = g.COMMIT_HASH
        LEFT JOIN pos p ON p.h = g.COMMIT_HASH
    """).fetchone()
    br_out = e["not_analysed_pos"] / e["not_analysed"]
    br_in = e["analysed_pos"] / e["analysed"]
    print(f"   NOT analysed: {e['not_analysed']:>7,} commits, base rate {br_out:.2%}")
    print(f"   analysed    : {e['analysed']:>7,} commits, base rate {br_in:.2%}")
    print(f"   analysed commits are {br_in / br_out:.2f}x more likely to be fault-inducing")
    out["selection"] = {"not_analysed": e["not_analysed"], "not_analysed_base": br_out,
                        "analysed": e["analysed"], "analysed_base": br_in,
                        "ratio": br_in / br_out}

    con.close()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
