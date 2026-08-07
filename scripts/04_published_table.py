# Check the arithmetic of Table 2 of Lomio et al. (doi:10.1007/s10664-022-10164-z) against the
# numbers stated in that paper's own abstract and text.
#
# Why this exists: the paper justifies SMOTE rebalancing by stating that fault-inducing commits are
# "less than 5%" of commits. If the published table does not support that figure, the preprocessing
# decision rests on a number the paper itself contradicts, and every downstream result inherits it.
# Transcribed by hand from the published Table 2 on 08.07.2026.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\04_published_table.py
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "results", "published_table_check.json")

# project, commits, faults, rules violated, rule occurrences
TABLE2 = [
    ("Accumulo", 2641, 2250, 118, 1429757),
    ("Ambari", 13397, 17722, 110, 41612),
    ("Atlas", 2336, 1990, 111, 35776),
    ("Aurora", 4012, 628, 90, 7526),
    ("Batik", 2097, 1160, 114, 31691),
    ("Beam", 2865, 1723, 109, 8449),
    ("Bcel", 10210, 3218, 98, 85018),
    ("Beanutils", 1324, 242, 81, 5182),
    ("Cli", 1192, 346, 81, 37408),
    ("Codec", 896, 182, 65, 58073),
    ("Cocoon", 1726, 327, 131, 2041),
    ("Collections", 2982, 135, 103, 11118),
    ("Configuration", 2895, 73, 96, 5612),
    ("Deamon", 980, 190, 30, 393),
    ("Dbcp", 1861, 284, 79, 3696),
    ("Dbutils", 645, 159, 40, 644),
    ("Digester", 2145, 149, 72, 4947),
    ("Exec", 617, 444, 57, 762),
    ("Felix", 596, 147, 104, 11340),
    ("FileUpload", 922, 282, 52, 769),
    ("Httpcomponents Client", 2867, 463, 97, 10803),
    ("HttpComponents Core", 1941, 188, 84, 9531),
    ("Io", 2118, 368, 85, 5849),
    ("Jelly", 1939, 56, 77, 5060),
    ("Jexl", 1551, 119, 101, 34994),
    ("Jxpath", 597, 265, 71, 4951),
    ("MINA Sshd", 1370, 1588, 97, 9031),
    ("Net", 2088, 438, 86, 41340),
    ("Ognl", 608, 3415, 90, 4945),
    ("Santuario", 2697, 1302, 107, 22398),
    ("Validator", 1339, 397, 61, 2050),
    ("Vfs", 2067, 84, 97, 3719),
    ("Zookeeper", 411, 1859, 70, 5023),
]

PRINTED_SUM = {"commits": 77932, "faults": 40470, "occurrences": 1941508}
TEXT_CLAIMS = {
    "imbalance": "commits labelled as fault inducing account for less than 5% of the total",
    "abstract_commits": 58125,
    "abstract_faults": 33865,
    "text_occurrences": 1914508,
    "text_rules": 174,
}
EXCLUDED = {"Batik", "Beam", "Cocoon", "Santuario"}  # stated exclusions, leaving 29 projects


def main():
    out = {}
    c = sum(r[1] for r in TABLE2)
    f = sum(r[2] for r in TABLE2)
    o = sum(r[4] for r in TABLE2)
    print(f"rows in Table 2: {len(TABLE2)}")
    print(f"\n{'':22} {'computed':>12} {'printed sum':>12} {'agrees':>8}")
    for name, comp, printed in (("commits", c, PRINTED_SUM["commits"]),
                                ("faults", f, PRINTED_SUM["faults"]),
                                ("occurrences", o, PRINTED_SUM["occurrences"])):
        print(f"{name:22} {comp:>12,} {printed:>12,} {str(comp == printed):>8}")
    out["column_sums"] = {"computed": {"commits": c, "faults": f, "occurrences": o},
                          "printed": PRINTED_SUM}

    # the faults column does not reach its own printed total; find out by how much and whether any
    # single listed project accounts for the gap exactly
    gap = f - PRINTED_SUM["faults"]
    if gap:
        print(f"\nfaults column overshoots its printed total by {gap:,}")
        exact = [r[0] for r in TABLE2 if r[2] == gap]
        print("   rows whose fault count equals that gap exactly:", exact or "none")
        print("   commits column, by contrast, agrees exactly, so the same Sum row")
        print("   includes those projects' commits while excluding their faults")
        out["faults_sum_gap"] = {"gap": gap, "rows_matching_gap": exact}

    print(f"\nfaults / commits over Table 2      {f / c:.2%}")
    print(f"the text says fault-inducing commits are  \"less than 5%\"")
    out["table2_fault_share"] = f / c

    print(f"\nabstract says {TEXT_CLAIMS['abstract_commits']:,} commits and "
          f"{TEXT_CLAIMS['abstract_faults']:,} faults -> "
          f"{TEXT_CLAIMS['abstract_faults'] / TEXT_CLAIMS['abstract_commits']:.2%}")
    out["abstract_fault_share"] = (TEXT_CLAIMS["abstract_faults"]
                                   / TEXT_CLAIMS["abstract_commits"])

    kept = [r for r in TABLE2 if r[0] not in EXCLUDED]
    ck, fk = sum(r[1] for r in kept), sum(r[2] for r in kept)
    print(f"\nafter the stated exclusion of {sorted(EXCLUDED)}:")
    print(f"   {len(kept)} projects, {ck:,} commits, {fk:,} faults -> {fk / ck:.2%}")
    print(f"   the abstract's {TEXT_CLAIMS['abstract_commits']:,} commits is "
          f"{'NOT ' if ck != TEXT_CLAIMS['abstract_commits'] else ''}this number")
    removed = c - ck
    print(f"   the stated exclusion removes {removed:,} tabulated commits")
    print(f"   the abstract's figure is a further {ck - TEXT_CLAIMS['abstract_commits']:,} lower, "
          f"and that reduction is not documented")
    out["after_exclusion"] = {"projects": len(kept), "commits": ck, "faults": fk,
                              "share": fk / ck, "commits_removed_by_exclusion": removed,
                              "undocumented_further_reduction":
                                  ck - TEXT_CLAIMS["abstract_commits"]}

    print("\nprojects where faults EXCEED commits, which no per-commit label can do:")
    worse = [(r[0], r[1], r[2], r[2] / r[1]) for r in TABLE2 if r[2] > r[1]]
    for name, cc, ff, ratio in sorted(worse, key=lambda x: -x[3]):
        print(f"   {name:24} {cc:>7,} commits  {ff:>7,} faults  x{ratio:.2f}")
    out["faults_exceed_commits"] = [{"project": n, "commits": cc, "faults": ff, "ratio": r}
                                    for n, cc, ff, r in worse]

    print("\nconcentration of rule occurrences:")
    top = sorted(TABLE2, key=lambda r: -r[4])[:3]
    for name, cc, _ff, _rv, occ in top:
        print(f"   {name:24} {occ:>10,}  = {occ / o:.1%} of all occurrences, "
              f"from {cc / c:.1%} of commits")
    out["occurrence_concentration"] = [{"project": n, "occurrences": occ,
                                        "share_of_occurrences": occ / o,
                                        "share_of_commits": cc / c}
                                       for n, cc, _f, _r, occ in top]

    print(f"\ntext says {TEXT_CLAIMS['text_occurrences']:,} occurrences, "
          f"Table 2 sums to {o:,}  (difference {abs(o - TEXT_CLAIMS['text_occurrences']):,})")
    out["occurrence_text_vs_table"] = {"text": TEXT_CLAIMS["text_occurrences"], "table": o}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
