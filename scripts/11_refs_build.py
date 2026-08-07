# Build the bibliography from live metadata. Nothing is cited that does not resolve.
#
# Every entry is fetched from Crossref by DOI, the returned title is compared with what we expected,
# and any mismatch is reported rather than silently accepted. Author surnames are screened per the
# programme's citation rule and the screen's decisions are printed for review rather than applied
# quietly.
#
# Run:  set PYTHONIOENCODING=utf-8 && py scripts\11_refs_build.py
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_MD = os.path.join(ROOT, "draft", "references.md")
OUT_JSON = os.path.join(ROOT, "integrity", "references_resolved.json")
MAILTO = "emil.huseynov.zabil@bsu.edu.az"

# key -> (doi, the title we believe it has)
REFS = {
    1: ("10.1007/s10664-022-10164-z",
        "A machine and deep learning analysis among SonarQube rules, product, and process metrics "
        "for fault prediction"),
    2: ("10.1145/3345629.3345630", "The Technical Debt Dataset"),
    3: ("10.1109/TSE.2018.2876537",
        "The Impact of Class Rebalancing Techniques on the Performance and Interpretation of "
        "Defect Prediction Models"),
    4: ("10.1109/TSE.2014.2322358",
        "Researcher Bias: The Use of Machine Learning in Software Defect Prediction"),
    5: ("10.1007/s10664-022-10186-7", "On effort-aware metrics for defect prediction"),
    6: ("10.1177/0272989X06295361",
        "Decision curve analysis: a novel method for evaluating prediction models"),
    7: ("10.1007/s10664-019-09750-5",
        "How developers engage with static analysis tools in different contexts"),
    8: ("10.1145/1083142.1083147", "When do changes induce fixes?"),
    9: ("10.1109/TSE.2012.70",
        "A large-scale empirical study of just-in-time quality assurance"),
    # Added after review round 2, which showed the degenerate-policy result is a rediscovery of
    # named baselines rather than a new observation. Cited so the paper's novelty claim can be
    # narrowed to what is actually new.
    10: ("10.1007/s10515-010-0069-5",
         "Defect prediction from static code features: current results, limitations, "
         "new approaches"),
    11: ("10.1145/3183339",
         "How Far We Have Progressed in the Journey? An Examination of Cross-Project "
         "Defect Prediction"),
    12: ("10.1109/ICSME.2017.51",
         "Supervised vs Unsupervised Models: A Holistic Look at Effort-Aware Just-in-Time "
         "Defect Prediction"),
    # In-journal anchors, added at venue fit Checkpoint 3. A journal's real scope is its printed
    # record, and a submission should position itself against what the venue has already published
    # on the same object rather than against the field in general.
    13: ("10.1007/s10664-023-10301-2",
         "Are automated static analysis tools worth it? An investigation into relative warning "
         "density and external software quality"),
    14: ("10.1007/s10664-021-10092-4",
         "Problems with SZZ and features: An empirical study of the state of practice of defect "
         "prediction data collection"),
    15: ("10.1007/s10664-020-09861-4",
         "On the assessment of software defect prediction models via ROC curves"),
    16: ("10.1007/s10664-022-10126-5",
         "On the adequacy of static analysis warnings with respect to code smell prediction"),
}

# Surnames ending in these forms are checked by hand before use. Chinese Yan, Persian and Arabic
# -yan, and South Indian -ian are not Armenian and stay; the point of the screen is to look, not to
# delete by suffix.
WATCH = re.compile(r"(ian|yan|yants)$", re.I)


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"paper-pipeline/1.0 (mailto:{MAILTO})"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (a + 1))
    raise SystemExit(f"could not resolve {url}: {last}")


def fmt_authors(auth):
    out = []
    for a in auth:
        fam = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        initials = "".join(p[0] for p in re.split(r"[\s\-]+", given) if p)
        out.append(f"{fam} {initials}".strip() if fam else given)
    return ", ".join(out)


def main():
    resolved, flags = {}, []
    lines = []
    for key in sorted(REFS):
        doi, expected = REFS[key]
        m = get(f"https://api.crossref.org/works/{doi}?mailto={MAILTO}")["message"]
        title = (m.get("title") or [""])[0]
        container = (m.get("container-title") or [""])
        container = container[0] if container else ""
        year = (m.get("published-print") or m.get("published-online") or m.get("issued")
                or {}).get("date-parts", [[None]])[0][0]
        auth = m.get("author") or []
        names = fmt_authors(auth)

        ok = expected.lower()[:40] in title.lower()
        if not ok:
            flags.append(f"[{key}] title mismatch: expected {expected!r}, got {title!r}")
        for a in auth:
            fam = (a.get("family") or "")
            if WATCH.search(fam):
                flags.append(f"[{key}] surname to check by hand: {fam}")

        resolved[key] = {"doi": doi, "title": title, "container": container,
                         "year": year, "authors": names, "title_matches": ok}
        lines.append(f"[{key}] {names} ({year}) {title}. *{container}*. "
                     f"https://doi.org/{doi}")
        print(f"[{key}] {'ok ' if ok else 'MISMATCH'} {title[:66]}")
        time.sleep(0.25)

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"resolved": resolved, "flags": flags}, f, indent=2, ensure_ascii=False)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# References\n\nEvery entry below resolved live against Crossref.\n\n")
        f.write("\n\n".join(lines) + "\n")

    print(f"\nresolved {len(resolved)} references")
    if flags:
        print("\nFLAGS, resolve each by hand before submitting:")
        for x in flags:
            print("  -", x)
    else:
        print("no flags")
    print("\nwrote", OUT_MD)


if __name__ == "__main__":
    main()
