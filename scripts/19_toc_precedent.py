# Check 3 of the venue fit gate: hard TOC precedent.
#
# The rule is that a journal's real scope is its printed record, not its aims page, and that fewer
# than three published articles matching our OBJECT and DATA TYPE is a FAIL however well the scope
# text reads. This queries OpenAlex for articles in Empirical Software Engineering only, filters to
# the last few years, and requires the title or abstract to carry our vocabulary.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\19_toc_precedent.py
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "research", "toc_precedent.json")
MAILTO = "emil.huseynov.zabil@bsu.edu.az"

# Empirical Software Engineering, Springer. ISSN checked against the journal page.
JOURNAL_ISSN = "1382-3256"
FROM_YEAR = 2020

QUERIES = [
    "static analysis warnings fault proneness",
    "SonarQube rules defect prediction",
    "just-in-time defect prediction commits effort aware",
    "code smells fault proneness empirical",
    "technical debt dataset SZZ fault inducing commits",
    "defect prediction evaluation baseline effort",
]

MUST = ["defect prediction", "fault-proneness", "fault proneness", "fault-inducing",
        "static analysis", "sonarqube", "warning", "code smell", "technical debt",
        "just-in-time", "szz", "quality gate", "bug prediction"]


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
    found = {}
    for q in QUERIES:
        url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(q)
               + f"&filter=locations.source.issn:{JOURNAL_ISSN},"
                 f"from_publication_date:{FROM_YEAR}-01-01"
               + f"&per-page=25&mailto={MAILTO}")
        d = get(url)
        for w in d.get("results", []):
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
            if not doi or "empirical software engineering" not in src.lower():
                continue
            abstract = rebuild(w.get("abstract_inverted_index"))
            hay = ((w.get("title") or "") + " " + abstract).lower()
            hits = [m for m in MUST if m in hay]
            if not hits:
                continue
            found.setdefault(doi, {
                "title": w.get("title"), "year": w.get("publication_year"),
                "venue": src, "cited": w.get("cited_by_count") or 0,
                "matched": hits[:5], "abstract": abstract[:320]})
        time.sleep(0.3)

    ranked = sorted(found.items(), key=lambda kv: (-(kv[1]["year"] or 0), -kv[1]["cited"]))
    print(f"Empirical Software Engineering articles from {FROM_YEAR} matching our object: "
          f"{len(ranked)}\n")
    for doi, v in ranked:
        print(f"  [{v['year']}] {(v['title'] or '')[:80]}")
        print(f"        doi:{doi}   cited {v['cited']}   matched on: {', '.join(v['matched'])}")

    verdict = "PASS" if len(ranked) >= 3 else "FAIL"
    print(f"\ncheck 3 (>= 3 in-journal precedents): {verdict}   ({len(ranked)} found)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"journal_issn": JOURNAL_ISSN, "from_year": FROM_YEAR,
                   "n_found": len(ranked), "verdict": verdict,
                   "precedents": [{"doi": d, **v} for d, v in ranked]}, f,
                  indent=2, ensure_ascii=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
