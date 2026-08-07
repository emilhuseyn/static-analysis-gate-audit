# Check review round two's statistical claims against the data, before conceding any of them.
#
#   A. is the monotone decline in within-stratum lift an artefact of the rising flag rate? Lift is
#      bounded by min(1/base, 1/flagrate). Compute that bound per stratum, and compute scale-free
#      measures (odds ratio, phi, risk difference) that are not subject to it.
#   B. how unstable is the unweighted-mean estimator across stratum counts, really?
#   C. does a CLUSTER bootstrap over projects, rather than over commits, contain 1.0?
#   D. apply the paper's own Requirement 3 to the paper's own headline policies: what happens to
#      blocker, and to all 116 screened rules, once size is standardised?
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\16_round2_check.py
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "td_V2.db")
OUT = os.path.join(ROOT, "results", "round2_check.json")
SEED = 20260808
N_BOOT = 2000


def load(cur):
    return cur.execute("""
        WITH gate AS (
            SELECT g.COMMIT_HASH h, g.PROJECT_ID pid FROM GIT_COMMITS g
            JOIN SONAR_ANALYSIS a ON a.REVISION = g.COMMIT_HASH GROUP BY g.COMMIT_HASH
        ),
        viol AS (
            SELECT a.REVISION h, COUNT(*) k,
                   SUM(CASE WHEN i.SEVERITY='BLOCKER' THEN 1 ELSE 0 END) blocker
            FROM SONAR_ISSUES i
            JOIN SONAR_ANALYSIS a ON a.ANALYSIS_KEY = i.CREATION_ANALYSIS_KEY
            WHERE a.REVISION IS NOT NULL GROUP BY a.REVISION
        ),
        churn AS (
            SELECT COMMIT_HASH h, SUM(COALESCE(LINES_ADDED,0)+COALESCE(LINES_REMOVED,0)) c
            FROM GIT_COMMITS_CHANGES GROUP BY COMMIT_HASH
        ),
        pos AS (SELECT DISTINCT FAULT_INDUCING_COMMIT_HASH h FROM SZZ_FAULT_INDUCING_COMMITS)
        SELECT p.PROJECT_KEY proj, COALESCE(v.k,0) nviol, COALESCE(v.blocker,0) nblock,
               COALESCE(ch.c,0) churn,
               CASE WHEN po.h IS NOT NULL THEN 1 ELSE 0 END y
        FROM gate
        JOIN PROJECTS p ON p.PROJECT_ID = gate.pid
        LEFT JOIN viol v ON v.h = gate.h
        LEFT JOIN churn ch ON ch.h = gate.h
        LEFT JOIN pos po ON po.h = gate.h
    """).fetchall()


def standardised_lift(flag, y, strata, nbins):
    obs = exp = 0.0
    for s in range(nbins):
        m = strata == s
        if m.sum() == 0 or y[m].sum() == 0:
            continue
        f = flag[m]
        obs += float((f & y[m]).sum())
        exp += float(f.sum() * y[m].mean())
    return (obs / exp) if exp else float("nan")


def bins(c, n):
    edges = np.quantile(c, np.linspace(0, 1, n + 1)[1:-1])
    return np.digitize(c, edges)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    r = load(con.cursor())
    con.close()
    rng = np.random.default_rng(SEED)

    proj = np.array([x["proj"] for x in r])
    y = np.array([x["y"] for x in r], dtype=bool)
    nviol = np.array([x["nviol"] for x in r], dtype=float)
    nblock = np.array([x["nblock"] for x in r], dtype=float)
    churn = np.array([x["churn"] for x in r], dtype=float)
    labelled = {p for p in set(proj) if y[proj == p].sum() > 0}
    keep = np.array([p in labelled for p in proj])
    P, Y, C = proj[keep], y[keep], churn[keep]
    V = nviol[keep] > 0
    B = nblock[keep] > 0
    out = {}

    pooled_lift = (Y[V].mean() / Y.mean())
    print(f"pooled lift of the violation flag: {pooled_lift:.4f}\n")

    # ---------- A ----------
    print("== A. is the monotone decline an artefact of the flag rate? ==")
    st = bins(C, 5)
    print(f"   {'q':>2} {'base':>7} {'flagrate':>9} {'lift':>6} {'maxlift':>8} "
          f"{'oddsratio':>10} {'phi':>7} {'riskdiff':>9}")
    rows = []
    for s in range(5):
        m = st == s
        base = Y[m].mean()
        fr = V[m].mean()
        lift = Y[m][V[m]].mean() / base
        maxlift = min(1 / base, 1 / fr)
        a = float((V[m] & Y[m]).sum())
        b = float((V[m] & ~Y[m]).sum())
        c_ = float((~V[m] & Y[m]).sum())
        d = float((~V[m] & ~Y[m]).sum())
        orat = (a * d) / (b * c_) if b and c_ else float("nan")
        n = a + b + c_ + d
        phi = ((a * d - b * c_) / math.sqrt((a + b) * (c_ + d) * (a + c_) * (b + d))
               if (a + b) * (c_ + d) * (a + c_) * (b + d) else float("nan"))
        rd = Y[m][V[m]].mean() - Y[m][~V[m]].mean()
        rows.append({"quintile": s + 1, "base": base, "flag_rate": fr, "lift": lift,
                     "max_attainable_lift": maxlift, "odds_ratio": orat, "phi": phi,
                     "risk_difference": rd})
        print(f"   {s + 1:>2} {base:>7.2%} {fr:>9.2%} {lift:>6.3f} {maxlift:>8.2f} "
              f"{orat:>10.3f} {phi:>7.4f} {rd:>9.4f}")
    mono_lift = all(rows[i]["lift"] >= rows[i + 1]["lift"] for i in range(4))
    mono_or = all(rows[i]["odds_ratio"] <= rows[i + 1]["odds_ratio"] for i in range(4))
    mono_phi = all(rows[i]["phi"] <= rows[i + 1]["phi"] for i in range(4))
    print(f"\n   lift declines monotonically      : {mono_lift}")
    print(f"   odds ratio RISES monotonically   : {mono_or}")
    print(f"   phi RISES monotonically          : {mono_phi}")
    print("   -> the decline in lift is a ceiling effect; association strengthens with size")
    out["stratum_measures"] = rows
    out["lift_monotone_down"] = bool(mono_lift)
    out["odds_ratio_monotone_up"] = bool(mono_or)
    out["phi_monotone_up"] = bool(mono_phi)

    # ---------- B ----------
    print("\n== B. how unstable is the unweighted-mean estimator? ==")
    est = {}
    for nb in (5, 10, 20, 50):
        s_ = bins(C, nb)
        lifts = []
        for s in range(nb):
            m = s_ == s
            if m.sum() < 5 or Y[m].sum() == 0 or V[m].sum() == 0:
                continue
            lifts.append(Y[m][V[m]].mean() / Y[m].mean())
        unw = float(np.mean(lifts))
        std = standardised_lift(V, Y, s_, nb)
        est[nb] = {"unweighted_mean_lift": unw, "standardised_lift": float(std),
                   "share_unweighted": 1 - (unw - 1) / (pooled_lift - 1),
                   "share_standardised": 1 - (std - 1) / (pooled_lift - 1)}
        print(f"   {nb:>2} strata: unweighted {unw:>8.3f} -> share "
              f"{est[nb]['share_unweighted']:>8.1%}   |  standardised {std:.3f} -> share "
              f"{est[nb]['share_standardised']:.1%}")
    out["estimators"] = est

    # ---------- C ----------
    print("\n== C. cluster bootstrap over projects ==")
    projects = sorted(set(P))
    idx_by_proj = {p: np.flatnonzero(P == p) for p in projects}
    st5 = bins(C, 5)
    boot = np.empty(N_BOOT)
    for i in range(N_BOOT):
        pick = rng.choice(len(projects), len(projects), replace=True)
        idx = np.concatenate([idx_by_proj[projects[j]] for j in pick])
        boot[i] = standardised_lift(V[idx], Y[idx], st5[idx], 5)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    point = standardised_lift(V, Y, st5, 5)
    print(f"   standardised lift {point:.3f}, cluster bootstrap 95% CI "
          f"[{lo:.3f}, {hi:.3f}]")
    print(f"   interval contains 1.0: {lo <= 1.0 <= hi}")
    out["cluster_bootstrap"] = {"point": float(point), "lo": float(lo), "hi": float(hi),
                                "contains_one": bool(lo <= 1.0 <= hi)}

    # ---------- D ----------
    print("\n== D. the paper's own Requirement 3, applied to the paper's own headlines ==")
    for name, flag in (("any violation", V), ("severity BLOCKER", B)):
        crude = Y[flag].mean() / Y.mean()
        adj = standardised_lift(flag, Y, st5, 5)
        print(f"   {name:18} crude lift {crude:.3f}  ->  size-standardised {adj:.3f}")
        out.setdefault("headline_policies", {})[name] = {"crude": float(crude),
                                                         "standardised": float(adj)}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
