# Leakage probe. Decides how a commit's feature vector may legally be built.
#
# SONAR_ISSUES carries CREATION_ANALYSIS_KEY, CREATION_DATE and CLOSE_DATE. A gate running on a commit
# can only see what exists at that moment. Two traps:
#   1. counting a violation against a commit that merely had it open, rather than introduced it,
#      mixes "this code is old and messy" with "this change is risky";
#   2. anything derived from CLOSE_DATE is information from the future by construction.
# This measures how much each choice would change the feature matrix before a single model is fitted.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\05_leak_probe.py
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "leak_probe.json")


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = {}

    print("== SONAR_ISSUES date coverage ==")
    r = cur.execute("""
        SELECT COUNT(*) n,
               SUM(CASE WHEN CREATION_DATE IS NOT NULL AND TRIM(CREATION_DATE)<>'' THEN 1 ELSE 0 END) has_create,
               SUM(CASE WHEN CLOSE_DATE   IS NOT NULL AND TRIM(CLOSE_DATE)  <>'' THEN 1 ELSE 0 END) has_close,
               SUM(CASE WHEN CREATION_ANALYSIS_KEY IS NOT NULL THEN 1 ELSE 0 END) has_key
        FROM SONAR_ISSUES""").fetchone()
    print(f"  issues                {r['n']:>10,}")
    print(f"  with creation date    {r['has_create']:>10,}  ({r['has_create']/r['n']:.1%})")
    print(f"  with close date       {r['has_close']:>10,}  ({r['has_close']/r['n']:.1%})")
    print(f"  with creation key     {r['has_key']:>10,}  ({r['has_key']/r['n']:.1%})")
    out["dates"] = dict(r)

    print("\n== status and resolution: which are future information? ==")
    for col in ("STATUS", "RESOLUTION"):
        print(f"  {col}:")
        counts = {}
        for row in cur.execute(
                f"SELECT {col} v, COUNT(*) n FROM SONAR_ISSUES GROUP BY {col} ORDER BY n DESC"):
            label = (str(row["v"]).strip() or "(empty)")
            counts[label] = row["n"]
            print(f"     {label[:24]:24} {row['n']:>9,}")
        out[col.lower()] = counts

    print("\n== issue mix, which the manuscript describes ==")
    for col in ("TYPE", "SEVERITY"):
        counts = {}
        for row in cur.execute(
                f"SELECT {col} v, COUNT(*) n FROM SONAR_ISSUES GROUP BY {col} ORDER BY n DESC"):
            label = (str(row["v"]).strip() or "(empty)")
            counts[label] = row["n"]
            print(f"  {col[:3]} {label[:22]:22} {row['n']:>9,}")
        out[f"mix_{col.lower()}"] = counts

    print("\n== violations introduced AT a commit versus open at that commit ==")
    # introduced: the issue's creation analysis points at this revision
    introduced = cur.execute("""
        SELECT COUNT(*) FROM SONAR_ISSUES i
        JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
        WHERE a.REVISION IS NOT NULL""").fetchone()[0]
    print(f"  issues tied to an introducing revision  {introduced:>10,}")

    # per-commit counts under the "introduced" reading
    rows = cur.execute("""
        SELECT a.REVISION rev, COUNT(*) k
        FROM SONAR_ISSUES i
        JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
        WHERE a.REVISION IS NOT NULL
        GROUP BY a.REVISION""").fetchall()
    counts = [r["k"] for r in rows]
    counts.sort()
    n = len(counts)
    print(f"  commits that introduce at least one     {n:>10,}")
    if n:
        print(f"    median introduced per such commit     {counts[n // 2]:>8,}")
        print(f"    p90                                   {counts[int(n * 0.9)]:>8,}")
        print(f"    max                                   {counts[-1]:>8,}")
    out["introduced"] = {"issues": introduced, "commits_with_any": n,
                         "median": counts[n // 2] if n else 0,
                         "p90": counts[int(n * 0.9)] if n else 0,
                         "max": counts[-1] if n else 0}

    # how many gateable commits introduce nothing at all: those are the easy negatives
    analysed = cur.execute("""
        SELECT COUNT(DISTINCT g.COMMIT_HASH) FROM GIT_COMMITS g
        JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH""").fetchone()[0]
    print(f"\n  gateable commits                        {analysed:>10,}")
    print(f"  of those, introducing no violation      {analysed - n:>10,}"
          f"  ({(analysed - n) / analysed:.1%})")
    out["gateable"] = {"commits": analysed, "introduce_none": analysed - n}

    # the decisive question: do fault-inducing commits introduce more violations than clean ones?
    print("\n== does the feature separate the classes at all? ==")
    r = cur.execute("""
        WITH intro AS (
            SELECT a.REVISION rev, COUNT(*) k
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL
            GROUP BY a.REVISION
        ),
        gate AS (
            SELECT DISTINCT g.COMMIT_HASH h FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        )
        SELECT
          SUM(CASE WHEN s.FAULT_INDUCING_COMMIT_HASH IS NOT NULL THEN 1 ELSE 0 END) pos,
          SUM(CASE WHEN s.FAULT_INDUCING_COMMIT_HASH IS NULL THEN 1 ELSE 0 END) neg,
          AVG(CASE WHEN s.FAULT_INDUCING_COMMIT_HASH IS NOT NULL
                   THEN COALESCE(i.k, 0) END) mean_pos,
          AVG(CASE WHEN s.FAULT_INDUCING_COMMIT_HASH IS NULL
                   THEN COALESCE(i.k, 0) END) mean_neg
        FROM gate
        LEFT JOIN intro i ON i.rev = gate.h
        LEFT JOIN (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH FROM SZZ_FAULT_INDUCING_COMMITS) s
               ON s.FAULT_INDUCING_COMMIT_HASH = gate.h
    """).fetchone()
    print(f"  fault-inducing commits {r['pos']:>8,}   mean violations introduced {r['mean_pos']:.2f}")
    print(f"  clean commits          {r['neg']:>8,}   mean violations introduced {r['mean_neg']:.2f}")
    out["separation"] = dict(r)

    con.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
