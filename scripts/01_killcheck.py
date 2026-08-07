# Data kill-check. Run BEFORE any design work: if the dataset cannot carry the study, say so now.
#
# The study needs four things from the Technical Debt Dataset:
#   1. SonarQube rule violations attributable to a commit
#   2. fault-inducing commit labels (SZZ)
#   3. a project identifier, so transfer across projects can be tested
#   4. a commit date, so splits can be time-ordered instead of random
# Anything missing changes the design or kills it.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\01_killcheck.py
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "killcheck.json")

WANT = ("commit", "fault", "issue", "project", "sonar", "rule", "metric", "szz", "refactor")


def main():
    if not os.path.isfile(DB):
        raise SystemExit(f"dataset missing: {DB}")
    size = os.path.getsize(DB)
    print(f"database: {size / 1e6:.1f} MB")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"\ntables: {len(tables)}")

    report = {"db_bytes": size, "tables": {}}
    for t in tables:
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except sqlite3.Error as e:
            print(f"  {t:38} unreadable: {e}")
            continue
        cols = [r["name"] for r in cur.execute(f'PRAGMA table_info("{t}")')]
        report["tables"][t] = {"rows": n, "columns": cols}
        flag = "  <-- relevant" if any(w in t.lower() for w in WANT) else ""
        print(f"  {t:38} {n:>10,} rows{flag}")
        if flag:
            print(f"      cols: {', '.join(cols[:14])}{' ...' if len(cols) > 14 else ''}")

    con.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
