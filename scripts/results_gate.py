# Single source of truth. Every number that appears in the manuscript is printed here, read from
# results/*.json. Nothing is retyped into the prose; if a figure is not in this output it may not
# appear in the paper.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\results_gate.py
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), "results")
OUT = os.path.join(RES, "results.json")


def load(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    base = load("base_rate.json")
    leak = load("leak_probe.json")
    triv = load("trivial_gate.json")
    rules = load("rule_screen.json")
    cert = load("certification.json")
    budget = load("budget_curve.json")
    pub = load("published_table_check.json")

    R = {}

    # ---- corpus ----
    R["corpus"] = {
        "commits_total": base["pooled"]["commits"],
        "gateable_commits": base["gateable"]["commits"],
        "gateable_share": base["coverage"]["share_of_commits"],
        "fault_inducing_gateable": base["gateable"]["fault_inducing"],
        "base_rate_pooled": base["pooled"]["base_rate"],
        "base_rate_gateable": base["gateable"]["base_rate"],
        "projects": len(base["per_project"]),
        "base_rate_min": base["spread"]["min"],
        "base_rate_median": base["spread"]["median"],
        "base_rate_max": base["spread"]["max"],
    }

    # ---- ceiling ----
    R["ceiling"] = triv["ceiling"]

    # ---- policies ----
    R["policies"] = {p["policy"]: {k: p[k] for k in
                                   ("precision", "recall", "alerts_per_1000_commits",
                                    "flagged", "lift_over_base")}
                     for p in triv["policies"]}

    # ---- rules ----
    R["rules"] = {
        "defined": 1819,
        "ever_fire": rules["rules_firing"],
        "tested": rules["rules_tested"],
        "min_flags": rules["min_flags"],
        "significant": rules["n_significant"],
        "useful": rules["n_useful"],
        "bh_threshold": rules["bh_threshold"],
        "best": rules["all_tested"][0],
        "weakest_significant": min(
            (t for t in rules["all_tested"] if t["significant"]),
            key=lambda t: t["precision"]),
        "top_by_volume": sorted(
            [t for t in rules["all_tested"] if t["significant"]],
            key=lambda t: -t["flags"])[:4],
    }

    # ---- certification ----
    R["certification"] = {
        "permutation": cert["permutation"],
        "bootstrap": cert["bootstrap"],
        "transfer": cert["transfer"],
        "time": {"early": {k: cert["time"]["early"][k] for k in
                           ("n", "base_rate", "precision", "recall", "lift")},
                 "late": {k: cert["time"]["late"][k] for k in
                          ("n", "base_rate", "precision", "recall", "lift")}},
        "concentration_top1": cert["concentration"][0],
        "concentration_top3": sum(c["share_violations"] for c in cert["concentration"][:3]),
    }

    # ---- budget curve ----
    R["budget"] = {"rows": budget["budgets"],
                   "churn_beats_violations_at": budget["churn_beats_violations_at"]}

    # ---- the published paper's own arithmetic ----
    R["published"] = {
        "table2_commits": pub["column_sums"]["computed"]["commits"],
        "table2_faults_computed": pub["column_sums"]["computed"]["faults"],
        "table2_faults_printed": pub["column_sums"]["printed"]["faults"],
        "faults_sum_gap": pub["faults_sum_gap"],
        "table2_fault_share": pub["table2_fault_share"],
        "abstract_fault_share": pub["abstract_fault_share"],
        "after_exclusion": pub["after_exclusion"],
        "faults_exceed_commits": pub["faults_exceed_commits"],
        "occurrence_concentration": pub["occurrence_concentration"][0],
        "occurrence_text_vs_table": pub["occurrence_text_vs_table"],
    }

    # ---- leaks ----
    R["leaks"] = {
        "issues": leak["dates"]["n"],
        "with_close_date": leak["dates"]["has_close"],
        "gateable_introducing_none": leak["gateable"]["introduce_none"],
        "gateable_introducing_none_share":
            leak["gateable"]["introduce_none"] / leak["gateable"]["commits"],
    }

    print("=" * 78)
    print("EVERY NUMBER THE MANUSCRIPT MAY USE")
    print("=" * 78)
    print(json.dumps(R, indent=2))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=2)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
