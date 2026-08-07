# The number the whole paper turns on: what fraction of commits actually induce a fault?
#
# Lomio et al. (doi:10.1007/s10664-022-10164-z) report AUC above 95 percent after rebalancing the
# classes with SMOTE. A CI gate does not run on a rebalanced world. It runs on this base rate. This
# script measures it, per project and pooled, and also measures how much of the commit history can be
# linked to a SonarQube analysis at all, since an unlinkable commit cannot be gated.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\02_base_rate.py
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "base_rate.json")


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = {}

    n_commits = cur.execute("SELECT COUNT(*) FROM GIT_COMMITS").fetchone()[0]
    n_distinct = cur.execute(
        "SELECT COUNT(DISTINCT COMMIT_HASH) FROM GIT_COMMITS").fetchone()[0]
    n_szz_rows = cur.execute("SELECT COUNT(*) FROM SZZ_FAULT_INDUCING_COMMITS").fetchone()[0]
    n_inducing = cur.execute(
        "SELECT COUNT(DISTINCT FAULT_INDUCING_COMMIT_HASH) FROM SZZ_FAULT_INDUCING_COMMITS"
    ).fetchone()[0]
    print(f"commits (rows)                 {n_commits:>10,}")
    print(f"commits (distinct hash)        {n_distinct:>10,}")
    print(f"SZZ rows                       {n_szz_rows:>10,}")
    print(f"distinct fault-inducing hashes {n_inducing:>10,}")

    # a fault-inducing hash only counts if it is a commit we actually have
    linked = cur.execute("""
        SELECT COUNT(DISTINCT s.FAULT_INDUCING_COMMIT_HASH)
        FROM SZZ_FAULT_INDUCING_COMMITS s
        JOIN GIT_COMMITS g ON g.COMMIT_HASH = s.FAULT_INDUCING_COMMIT_HASH
    """).fetchone()[0]
    print(f"of those, present in GIT_COMMITS {linked:>8,}"
          f"   ({linked / max(n_inducing, 1):.1%} of SZZ hashes)")

    base = linked / n_distinct if n_distinct else 0
    print(f"\nPOOLED BASE RATE               {base:.4%}")
    out["pooled"] = {"commits": n_distinct, "fault_inducing": linked, "base_rate": base,
                     "szz_rows": n_szz_rows, "szz_distinct": n_inducing}

    # how much of the history is even gateable: a commit needs a SonarQube analysis
    n_an = cur.execute("SELECT COUNT(*) FROM SONAR_ANALYSIS").fetchone()[0]
    n_an_rev = cur.execute(
        "SELECT COUNT(DISTINCT REVISION) FROM SONAR_ANALYSIS WHERE REVISION IS NOT NULL"
    ).fetchone()[0]
    analysed = cur.execute("""
        SELECT COUNT(DISTINCT g.COMMIT_HASH)
        FROM GIT_COMMITS g
        JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
    """).fetchone()[0]
    print(f"\nSonarQube analyses             {n_an:>10,}"
          f"   (distinct revisions {n_an_rev:,})")
    print(f"commits with an analysis       {analysed:>10,}"
          f"   ({analysed / max(n_distinct, 1):.1%} of commits)")
    out["coverage"] = {"analyses": n_an, "distinct_revisions": n_an_rev,
                       "commits_with_analysis": analysed,
                       "share_of_commits": analysed / max(n_distinct, 1)}

    # and the base rate among the commits that could actually be gated
    gate_pos = cur.execute("""
        SELECT COUNT(DISTINCT g.COMMIT_HASH)
        FROM GIT_COMMITS g
        JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        JOIN SZZ_FAULT_INDUCING_COMMITS s ON s.FAULT_INDUCING_COMMIT_HASH = g.COMMIT_HASH
    """).fetchone()[0]
    gate_base = gate_pos / analysed if analysed else 0
    print(f"\nBASE RATE AMONG GATEABLE COMMITS {gate_base:.4%}"
          f"   ({gate_pos:,} of {analysed:,})")
    out["gateable"] = {"commits": analysed, "fault_inducing": gate_pos, "base_rate": gate_base}

    print("\nper project:")
    rows = cur.execute("""
        SELECT p.PROJECT_KEY AS proj,
               COUNT(DISTINCT g.COMMIT_HASH) AS commits,
               COUNT(DISTINCT s.FAULT_INDUCING_COMMIT_HASH) AS inducing
        FROM PROJECTS p
        JOIN GIT_COMMITS g ON g.PROJECT_ID = p.PROJECT_ID
        LEFT JOIN SZZ_FAULT_INDUCING_COMMITS s
               ON s.FAULT_INDUCING_COMMIT_HASH = g.COMMIT_HASH
        GROUP BY p.PROJECT_KEY
        ORDER BY commits DESC
    """).fetchall()
    per = []
    for r in rows:
        br = r["inducing"] / r["commits"] if r["commits"] else 0
        per.append({"project": r["proj"], "commits": r["commits"],
                    "fault_inducing": r["inducing"], "base_rate": br})
        print(f"   {r['proj'][:34]:34} {r['commits']:>7,} commits  "
              f"{r['inducing']:>6,} inducing  {br:>7.2%}")
    out["per_project"] = per
    if per:
        rates = sorted(x["base_rate"] for x in per)
        print(f"\nbase rate across projects: min {rates[0]:.2%}, "
              f"median {rates[len(rates) // 2]:.2%}, max {rates[-1]:.2%}")
        out["spread"] = {"min": rates[0], "median": rates[len(rates) // 2], "max": rates[-1]}

    con.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
