# Verify the zero-label projects before anything is built on them.
#
# 02_base_rate.py found three projects with no fault-inducing commits at all, one of them (hive)
# with 15,733 commits. That is either a real property of the dataset or a defect in my join. It has
# to be settled before it becomes a claim.
#
# Checks:
#   1. does SZZ hold rows for those projects under their own PROJECT_ID?
#   2. do the fault-FIXING commits for those projects exist, i.e. did SZZ run and find nothing, or
#      did it never run?
#   3. do those projects have JIRA issues at all, since SZZ needs issue links to start from?
#   4. does the SZZ PROJECT_ID agree with the PROJECT_ID of the commit it names?
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\03_verify_labels.py
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "label_verification.json")


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = {}

    print("== SZZ rows per project, by SZZ's own PROJECT_ID ==")
    rows = cur.execute("""
        SELECT p.PROJECT_KEY AS proj,
               COUNT(*) AS szz_rows,
               COUNT(DISTINCT s.FAULT_INDUCING_COMMIT_HASH) AS inducing,
               COUNT(DISTINCT s.FAULT_FIXING_COMMIT_HASH) AS fixing
        FROM PROJECTS p
        LEFT JOIN SZZ_FAULT_INDUCING_COMMITS s ON s.PROJECT_ID = p.PROJECT_ID
        GROUP BY p.PROJECT_KEY
        ORDER BY szz_rows ASC
    """).fetchall()
    per = [{"project": r["proj"], "szz_rows": r["szz_rows"],
            "inducing": r["inducing"], "fixing": r["fixing"]} for r in rows]
    for r in per[:12]:
        print(f"   {r['project'][:32]:32} rows {r['szz_rows']:>7,}  "
              f"inducing {r['inducing']:>6,}  fixing {r['fixing']:>6,}")
    out["szz_per_project"] = per

    empty = [r["project"] for r in per if r["szz_rows"] == 0]
    print("\nprojects with NO SZZ rows at all:", empty or "none")
    out["projects_without_szz"] = empty

    print("\n== JIRA issues and commits for those projects ==")
    detail = []
    for proj in empty:
        r = cur.execute("""
            SELECT p.PROJECT_KEY AS proj, p.PROJECT_ID AS pid,
                   (SELECT COUNT(*) FROM JIRA_ISSUES j WHERE j.PROJECT_ID = p.PROJECT_ID) AS jira,
                   (SELECT COUNT(*) FROM GIT_COMMITS g WHERE g.PROJECT_ID = p.PROJECT_ID) AS commits,
                   (SELECT COUNT(*) FROM SONAR_ANALYSIS a WHERE a.PROJECT_ID = p.PROJECT_ID) AS analyses,
                   (SELECT COUNT(*) FROM SONAR_ISSUES i WHERE i.PROJECT_ID = p.PROJECT_ID) AS issues
            FROM PROJECTS p WHERE p.PROJECT_KEY = ?
        """, (proj,)).fetchone()
        d = dict(r)
        detail.append(d)
        print(f"   {d['proj'][:24]:24} commits {d['commits']:>7,}  jira {d['jira']:>6,}  "
              f"analyses {d['analyses']:>6,}  sonar issues {d['issues']:>8,}")
    out["empty_project_detail"] = detail

    print("\n== does SZZ's PROJECT_ID agree with the commit's own PROJECT_ID? ==")
    mismatch = cur.execute("""
        SELECT COUNT(*) FROM SZZ_FAULT_INDUCING_COMMITS s
        JOIN GIT_COMMITS g ON g.COMMIT_HASH = s.FAULT_INDUCING_COMMIT_HASH
        WHERE g.PROJECT_ID <> s.PROJECT_ID
    """).fetchone()[0]
    total_join = cur.execute("""
        SELECT COUNT(*) FROM SZZ_FAULT_INDUCING_COMMITS s
        JOIN GIT_COMMITS g ON g.COMMIT_HASH = s.FAULT_INDUCING_COMMIT_HASH
    """).fetchone()[0]
    print(f"   joined rows {total_join:,}, project mismatches {mismatch:,}")
    out["project_id_mismatch"] = {"joined": total_join, "mismatched": mismatch}

    print("\n== JIRA issue types present, which is what SZZ starts from ==")
    for r in cur.execute("""
        SELECT TYPE, COUNT(*) n FROM JIRA_ISSUES GROUP BY TYPE ORDER BY n DESC LIMIT 10
    """):
        print(f"   {str(r['TYPE'])[:30]:30} {r['n']:>8,}")

    con.close()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
