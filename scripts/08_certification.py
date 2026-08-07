# Certification. Nothing above is allowed into the paper until it survives this.
#
#   1. concentration - is one project supplying the signal, as Accumulo does in the published table?
#   2. transfer      - does the trivial gate hold per project, or is it an average over incompatible
#                      repositories?
#   3. time          - does it hold in the later half of each project's history, which is the only
#                      half a team deploying today would live in?
#   4. permutation   - with the labels shuffled, what does the gate score? Anything it beats the null
#                      by is the whole of its value.
#   5. bootstrap     - an interval on every headline number, so none of them is quoted bare.
#
# Seeded. Rerunning reproduces the published values exactly.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\08_certification.py
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "certification.json")

SEED = 20260808
N_PERM = 2000
N_BOOT = 2000


def load(cur):
    """One row per gateable commit: project, date, flagged by the trivial gate, fault-inducing."""
    rows = cur.execute("""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid, a.DATE d
            FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH
            GROUP BY g.COMMIT_HASH
        ),
        intro AS (
            SELECT DISTINCT a.REVISION h FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS),
        cnt AS (
            SELECT a.REVISION h, COUNT(*) k FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        )
        SELECT p.PROJECT_KEY proj, gate.d date,
               CASE WHEN i.h IS NOT NULL THEN 1 ELSE 0 END flagged,
               CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END y,
               COALESCE(c.k, 0) nviol
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN intro i ON i.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
        LEFT JOIN cnt c ON c.h = gate.h
    """).fetchall()
    proj = np.array([r["proj"] for r in rows])
    date = np.array([r["date"] or "" for r in rows])
    flag = np.array([r["flagged"] for r in rows], dtype=bool)
    y = np.array([r["y"] for r in rows], dtype=bool)
    nv = np.array([r["nviol"] for r in rows], dtype=float)
    return proj, date, flag, y, nv


def score(flag, y):
    n = len(y)
    fl = int(flag.sum())
    tp = int((flag & y).sum())
    pos = int(y.sum())
    return {"n": n, "positives": pos, "base_rate": pos / n if n else 0.0,
            "flagged": fl, "tp": tp,
            "precision": tp / fl if fl else 0.0,
            "recall": tp / pos if pos else 0.0,
            "alerts_per_1000": 1000 * fl / n if n else 0.0,
            "lift": ((tp / fl) / (pos / n)) if fl and pos else 0.0}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    proj, date, flag, y, nv = load(cur)
    con.close()
    rng = np.random.default_rng(SEED)

    # Certify the PRIMARY population, the 28 projects carrying at least one SZZ label. Round two
    # caught this script still certifying the 31-project sensitivity population while the manuscript
    # headlined the 28-project numbers, so the permutation null and the bootstrap were not testing
    # any figure the paper actually reports.
    labelled = {p for p in set(proj) if y[proj == p].sum() > 0}
    keep = np.array([p in labelled for p in proj])
    dropped = sorted(set(proj) - labelled)
    print(f"primary population: {len(labelled)} projects, {int(keep.sum()):,} commits")
    print(f"excluded, no SZZ label: {dropped}\n")
    proj, date, flag, y, nv = proj[keep], date[keep], flag[keep], y[keep], nv[keep]

    out = {"seed": SEED, "n_permutations": N_PERM, "n_bootstrap": N_BOOT,
           "population": {"projects": len(labelled), "commits": int(len(y)),
                          "excluded_projects": dropped}}

    overall = score(flag, y)
    print(f"pooled: n {overall['n']:,}  base {overall['base_rate']:.2%}  "
          f"prec {overall['precision']:.2%}  rec {overall['recall']:.2%}  "
          f"lift {overall['lift']:.2f}x")
    out["pooled"] = overall

    # ---- 1. concentration ----
    print("\n== concentration of rule occurrences ==")
    tot = nv.sum()
    shares = []
    for p in sorted(set(proj)):
        m = proj == p
        shares.append((p, float(nv[m].sum() / tot), int(m.sum()) / len(proj)))
    shares.sort(key=lambda x: -x[1])
    for p, s_occ, s_com in shares[:5]:
        print(f"   {p[:30]:30} {s_occ:>6.1%} of violations from {s_com:>6.1%} of commits")
    out["concentration"] = [{"project": p, "share_violations": s, "share_commits": c}
                            for p, s, c in shares]
    print(f"   top three together: {sum(s for _, s, _ in shares[:3]):.1%} of all violations")

    # ---- 2. transfer ----
    print("\n== the trivial gate, per project ==")
    per = []
    for p in sorted(set(proj)):
        m = proj == p
        if y[m].sum() == 0:
            continue
        s = score(flag[m], y[m])
        s["project"] = p
        per.append(s)
    per.sort(key=lambda s: -s["precision"])
    for s in per[:5] + [{"project": "..."}] + per[-5:]:
        if s["project"] == "...":
            print("   ...")
            continue
        print(f"   {s['project'][:28]:28} base {s['base_rate']:>6.2%}  "
              f"prec {s['precision']:>6.2%}  rec {s['recall']:>6.2%}  lift {s['lift']:>5.2f}x")
    lifts = [s["lift"] for s in per]
    below = [s["project"] for s in per if s["lift"] <= 1.0]
    print(f"\n   projects with a positive base rate: {len(per)}")
    print(f"   lift: min {min(lifts):.2f}x, median {float(np.median(lifts)):.2f}x, "
          f"max {max(lifts):.2f}x")
    print(f"   projects where the gate is NO BETTER than the base rate: "
          f"{len(below)}  {below[:6]}")
    out["per_project"] = per
    out["transfer"] = {"n_projects": len(per), "lift_min": min(lifts),
                       "lift_median": float(np.median(lifts)), "lift_max": max(lifts),
                       "projects_no_better": below}

    # ---- 3. time ----
    print("\n== early half against late half, within each project ==")
    early_f, early_y, late_f, late_y = [], [], [], []
    for p in sorted(set(proj)):
        m = proj == p
        if m.sum() < 20 or y[m].sum() == 0:
            continue
        order = np.argsort(date[m])
        half = len(order) // 2
        idx = np.flatnonzero(m)
        e, l = idx[order[:half]], idx[order[half:]]
        early_f.append(flag[e]); early_y.append(y[e])
        late_f.append(flag[l]); late_y.append(y[l])
    e = score(np.concatenate(early_f), np.concatenate(early_y))
    l = score(np.concatenate(late_f), np.concatenate(late_y))
    for name, s in (("early", e), ("late", l)):
        print(f"   {name:6} n {s['n']:>7,}  base {s['base_rate']:>6.2%}  "
              f"prec {s['precision']:>6.2%}  rec {s['recall']:>6.2%}  lift {s['lift']:.2f}x")
    out["time"] = {"early": e, "late": l}

    # ---- 4. permutation null ----
    print(f"\n== permutation null, {N_PERM:,} shuffles of the labels ==")
    obs = overall["precision"]
    null = np.empty(N_PERM)
    yy = y.copy()
    for i in range(N_PERM):
        rng.shuffle(yy)
        fl = int(flag.sum())
        null[i] = (flag & yy).sum() / fl if fl else 0.0
    p_val = float((null >= obs).sum() + 1) / (N_PERM + 1)
    print(f"   observed precision {obs:.4%}")
    print(f"   null mean {null.mean():.4%}, sd {null.std():.4%}, "
          f"max {null.max():.4%}")
    print(f"   p = {p_val:.4g}   (the null sits at the base rate, as it must)")
    out["permutation"] = {"observed_precision": obs, "null_mean": float(null.mean()),
                          "null_sd": float(null.std()), "null_max": float(null.max()),
                          "p_value": p_val}

    # ---- 5. bootstrap ----
    print(f"\n== bootstrap, {N_BOOT:,} resamples ==")
    n = len(y)
    prec_b, rec_b, lift_b = np.empty(N_BOOT), np.empty(N_BOOT), np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, n)
        s = score(flag[idx], y[idx])
        prec_b[i], rec_b[i], lift_b[i] = s["precision"], s["recall"], s["lift"]
    for name, arr, point in (("precision", prec_b, overall["precision"]),
                             ("recall", rec_b, overall["recall"]),
                             ("lift", lift_b, overall["lift"])):
        lo, hi = np.percentile(arr, [2.5, 97.5])
        fmt = "{:.2%}" if name != "lift" else "{:.2f}x"
        print(f"   {name:10} {fmt.format(point)}   95% CI ["
              f"{fmt.format(lo)}, {fmt.format(hi)}]")
        out.setdefault("bootstrap", {})[name] = {"point": point, "lo": float(lo),
                                                 "hi": float(hi)}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
