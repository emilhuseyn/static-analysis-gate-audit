# Novelty gate for paper 6, run BEFORE any analysis.
#
# The topic is an audit of a specific published result: Lomio, Moreschini and Lenarduzzi report
# AUC above 95 percent for fault-inducing commit prediction from SonarQube rules on the Technical
# Debt Dataset (doi:10.1007/s10664-022-10164-z), after SMOTE rebalancing, and themselves call the
# figure "better than expected". The proposed contribution is what that model is worth to somebody
# configuring a CI quality gate: at the real base rate, under a fixed review budget, against trivial
# baselines, and whether a surviving rule set transfers across projects.
#
# Two things must be established before a line of analysis is written:
#   A. has this specific result already been audited or replicated?
#   B. how occupied is the general methodological claim (rebalancing and threshold-free metrics
#      flatter defect prediction)? It is certainly not empty, and the delta has to be stated against
#      it honestly rather than pretending otherwise.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\00_novelty_screen.py
import json
import os
import re
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "research", "novelty_screen.json")
MAILTO = "emil.huseynov.zabil@bsu.edu.az"

VENUE_OK = re.compile(
    r"(software|empirical|systems|informatics|computing|security|"
    r"acm|ieee|arxiv|maintenance|evolution|quality|debt)", re.I)

QUERIES = {
    "A. audit or replication of this specific result": [
        "SonarQube rules fault prediction replication technical debt dataset",
        "SonarQube quality gate rules fault-inducing commits evaluation critique",
        "technical debt dataset SonarQube fault proneness reproduction",
    ],
    "B. rebalancing and metric choice inflating defect prediction": [
        "class rebalancing SMOTE impact defect prediction model performance",
        "biased performance metrics software defect prediction AUC",
        "oversampling before cross validation data leakage defect prediction",
    ],
    "C. deployment-realistic evaluation of static analysis warnings": [
        "static analysis warnings actionable alerts developers budget precision",
        "effort aware evaluation static analysis warning prioritization",
        "cost of false alarms static analysis adoption continuous integration",
    ],
    "D. cross-project transfer of a warning or rule set": [
        "cross project defect prediction transfer static analysis rules",
        "leave one project out generalization code smell fault proneness",
    ],
}

MUST = ["defect prediction", "fault prediction", "fault-proneness", "fault proneness",
        "static analysis", "sonarqube", "warning", "code smell", "rebalanc", "smote",
        "quality gate", "bug prediction", "fault-inducing", "technical debt"]


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"paper-pipeline/1.0 (mailto:{MAILTO})"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (a + 1))
    return {"results": [], "error": str(last)}


def rebuild(inv):
    if not inv:
        return ""
    pos = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[k] for k in sorted(pos))


def main():
    report = {}
    for bucket, queries in QUERIES.items():
        print("\n" + "=" * 78)
        print(bucket)
        found, dropped = {}, 0
        for qi, q in enumerate(queries):
            d = get("https://api.openalex.org/works?search=" + urllib.parse.quote(q)
                    + f"&per-page=10&sort=relevance_score:desc&mailto={MAILTO}")
            for pos, w in enumerate(d.get("results", [])):
                doi = (w.get("doi") or "").replace("https://doi.org/", "")
                src = ((w.get("primary_location") or {}).get("source") or {}).get(
                    "display_name") or ""
                if not doi or not VENUE_OK.search(src) or doi in found:
                    continue
                abstract = rebuild(w.get("abstract_inverted_index"))
                hay = ((w.get("title") or "") + " " + abstract).lower()
                hits = [m for m in MUST if m in hay]
                if not hits:
                    dropped += 1
                    continue
                found[doi] = {
                    "title": w.get("title"), "year": w.get("publication_year"),
                    "venue": src, "cited": w.get("cited_by_count") or 0,
                    "matched": hits[:4], "abstract": abstract[:700],
                    "_rank": qi * 100 + pos,
                }
            time.sleep(0.3)

        ranked = sorted(found.items(), key=lambda kv: kv[1]["_rank"])[:6]
        report[bucket] = {"n": len(found), "dropped": dropped,
                          "closest": [{"doi": d, **{k: v for k, v in val.items() if k != "_rank"}}
                                      for d, val in ranked]}
        print(f"  on-topic hits: {len(found)}   (dropped off-topic: {dropped})")
        for doi, v in ranked:
            print(f"\n  [{v['year']}] {(v['title'] or '')[:82]}")
            print(f"       {v['venue'][:60]} | doi:{doi} | cited {v['cited']}")
            if v["abstract"]:
                print(f"       {v['abstract'][:260]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
