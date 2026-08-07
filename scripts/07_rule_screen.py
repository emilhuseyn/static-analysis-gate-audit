# Per-rule screen: does ANY single SonarQube rule earn a place in a CI gate?
#
# This is the only result a practitioner can act on directly. 1,819 rules exist, so testing each one
# against the base rate without correction would manufacture "significant" rules by arithmetic alone.
# Every rule is tested one-sided against the gateable base rate with an exact binomial test, and the
# whole family is corrected with Benjamini-Hochberg at q = 0.05.
#
# A rule has to clear three bars, not one:
#   1. precision significantly above the base rate after correction
#   2. a precision worth a human's time, not merely a non-zero difference
#   3. an alert rate a team could actually absorb
# A rule that fires four times in 67,550 commits is not a gate, however clean its precision.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\07_rule_screen.py
import json
import os
import sqlite3

from scipy.stats import binomtest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "rule_screen.json")

Q = 0.05
MIN_FLAGS = 50          # below this a rule cannot be evaluated, let alone deployed
USEFUL_PRECISION = 0.50  # one in two alerts real; below this reviewers disengage


def benjamini_hochberg(pvals, q):
    """Return the p-value threshold below which a test is significant, or 0.0 if none is."""
    m = len(pvals)
    ordered = sorted(pvals)
    thresh = 0.0
    for i, p in enumerate(ordered, start=1):
        if p <= i * q / m:
            thresh = p
    return thresh


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Restricted to projects that carry at least one SZZ label. A project where no commit can be a
    # positive contributes only guaranteed false positives, and in this corpus the three such
    # projects supply half of all introduced violations, which is enough to reverse a severity
    # result. Review round 1 caught this; see review/round1.md.
    LABELLED = """
        SELECT PROJECT_ID FROM PROJECTS WHERE PROJECT_ID IN (
            SELECT DISTINCT g.PROJECT_ID FROM GIT_COMMITS g
            JOIN SZZ_FAULT_INDUCING_COMMITS s ON s.FAULT_INDUCING_COMMIT_HASH = g.COMMIT_HASH)
    """
    gate = cur.execute(f"""
        SELECT COUNT(DISTINCT g.COMMIT_HASH) n FROM GIT_COMMITS g
        JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        WHERE g.PROJECT_ID IN ({LABELLED})""").fetchone()["n"]
    pos = cur.execute(f"""
        SELECT COUNT(DISTINCT g.COMMIT_HASH) n FROM GIT_COMMITS g
        JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
        JOIN SZZ_FAULT_INDUCING_COMMITS s ON s.FAULT_INDUCING_COMMIT_HASH = g.COMMIT_HASH
        WHERE g.PROJECT_ID IN ({LABELLED})""").fetchone()["n"]
    base = pos / gate
    print(f"gateable commits {gate:,}   fault-inducing {pos:,}   base rate {base:.4%}")
    print("(28 labelled projects; the three without SZZ labels are excluded)\n")

    print("counting per-rule flags and hits (one pass) ...")
    rows = cur.execute(f"""
        WITH gate AS (
            SELECT DISTINCT g.COMMIT_HASH h FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
            WHERE g.PROJECT_ID IN ({LABELLED})
        ),
        intro AS (
            SELECT DISTINCT i.RULE rule, a.REVISION rev
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL AND i.RULE IS NOT NULL
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT intro.rule rule,
               COUNT(*) flags,
               SUM(CASE WHEN p.h IS NOT NULL THEN 1 ELSE 0 END) hits
        FROM intro
        JOIN gate ON gate.h = intro.rev
        LEFT JOIN pos p ON p.h = intro.rev
        GROUP BY intro.rule
    """).fetchall()
    print(f"rules that fire at all: {len(rows):,}")

    cand = [r for r in rows if r["flags"] >= MIN_FLAGS]
    print(f"rules firing at least {MIN_FLAGS} times: {len(cand):,}")

    tested = []
    for r in cand:
        p = float(binomtest(r["hits"], r["flags"], base, alternative="greater").pvalue)
        tested.append({"rule": r["rule"], "flags": int(r["flags"]), "hits": int(r["hits"]),
                       "precision": r["hits"] / r["flags"],
                       "alerts_per_1000": 1000 * r["flags"] / gate,
                       "lift": (r["hits"] / r["flags"]) / base, "p": p})

    thresh = benjamini_hochberg([t["p"] for t in tested], Q)
    for t in tested:
        t["significant"] = bool(t["p"] <= thresh)
    n_sig = sum(1 for t in tested if t["significant"])
    print(f"\nBenjamini-Hochberg at q={Q}: threshold p <= {thresh:.3g}, "
          f"{n_sig:,} of {len(tested):,} rules significant")

    useful = [t for t in tested if t["significant"] and t["precision"] >= USEFUL_PRECISION]
    print(f"of those, reaching {USEFUL_PRECISION:.0%} precision: {len(useful):,}")

    print("\n== the ten highest-precision rules that survive correction ==")
    top = sorted([t for t in tested if t["significant"]],
                 key=lambda t: -t["precision"])[:10]
    if not top:
        print("   none")
    for t in top:
        print(f"   {t['rule'][:44]:44} prec {t['precision']:>6.2%}  "
              f"flags {t['flags']:>6,}  {t['alerts_per_1000']:>5.1f}/1k  lift {t['lift']:.2f}x")

    print("\n== the ten that would generate the most alerts ==")
    for t in sorted([t for t in tested if t["significant"]],
                    key=lambda t: -t["flags"])[:10]:
        print(f"   {t['rule'][:44]:44} prec {t['precision']:>6.2%}  "
              f"flags {t['flags']:>6,}  {t['alerts_per_1000']:>5.1f}/1k  lift {t['lift']:.2f}x")

    best = max(tested, key=lambda t: t["precision"]) if tested else None
    if best:
        print(f"\nhighest precision of any rule firing >= {MIN_FLAGS} times: "
              f"{best['precision']:.2%}  ({best['rule']}, {best['flags']:,} flags)")

    # significance is nearly free at this sample size; say so with a number rather than a word
    if tested:
        sig = [t for t in tested if t["significant"]]
        if sig:
            worst = min(sig, key=lambda t: t["precision"])
            print(f"the WEAKEST rule that still counts as significant: "
                  f"{worst['precision']:.2%} precision ({worst['rule']}), "
                  f"against a base rate of {base:.2%}")

    out = {"gateable": gate, "positives": pos, "base_rate": base,
           "q": Q, "min_flags": MIN_FLAGS, "useful_precision": USEFUL_PRECISION,
           "rules_firing": len(rows), "rules_tested": len(tested),
           "bh_threshold": thresh, "n_significant": n_sig,
           "n_useful": len(useful),
           "useful_rules": sorted(useful, key=lambda t: -t["precision"]),
           "all_tested": sorted(tested, key=lambda t: -t["precision"])}
    con.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
