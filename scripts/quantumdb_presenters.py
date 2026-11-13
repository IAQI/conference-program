#!/usr/bin/env python3
"""
Take the presenting authors of a conference from QuantumDB.

    python3 quantumdb_presenters.py --venue qcrypt --year 2026 [--site .] [--check]

QuantumDB (https://quantumdb.iaqi.org, data under CC0) records, for every
talk and poster of QIP, QCrypt and TQC, which author presented it, and the
YouTube recording. This script downloads the conference export
(/api/v1/export/conferences/<venue>-<year>), matches its publications to
data/accepted-papers-YEAR.json and data/posters-YEAR.json by title (QuantumDB
does not know HotCRP ids) and writes

  data/presenters-YEAR.yml     "pid": ["First Last"], spelled as in the
                               accepted-papers data, so the templates can
                               highlight the name

merged with data/presenters-overrides-YEAR.yml, which always wins. It is an
alternative to mark_presenters.py (which reads registration exports): use
whichever source you have. Publications it cannot match, and recordings
whose YouTube id differs from data/videos-YEAR.yml, are reported.

--from-json FILE reads a saved export instead of downloading it.
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import yaml

API = "https://quantumdb.iaqi.org/api/v1/export/conferences/{venue}-{year}"
THRESHOLD = 0.9


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def author_name(author):
    return " ".join(x for x in (author.get("first"), author.get("last")) if x).strip()


def same_person(ours, theirs):
    """Whether two spellings name the same person (accents, initials, middle names)."""
    a, b = normalize(ours).split(), normalize(theirs).split()
    if not a or not b:
        return False
    if a == b:
        return True
    # same last name, and first names agree on their initial
    return a[-1] == b[-1] and a[0][0] == b[0][0]


def load_papers(site, year):
    papers = {}
    for name in (f"accepted-papers-{year}.json", f"posters-{year}.json"):
        path = site / "data" / name
        if path.exists():
            for p in json.loads(path.read_text(encoding="utf-8")):
                papers[str(int(p["pid"]))] = p
    return papers


def best_paper(title, papers):
    scored = sorted(((similarity(title, p.get("title", "")), pid) for pid, p in papers.items()), reverse=True)
    if not scored or scored[0][0] < THRESHOLD:
        return None, scored[0] if scored else None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.01:
        return None, scored[0]  # two papers with (nearly) the same title: let a human decide
    return scored[0][1], scored[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--venue", required=True, choices=["qip", "qcrypt", "tqc"])
    parser.add_argument("--year", required=True)
    parser.add_argument("--site", default=".")
    parser.add_argument("--from-json", metavar="FILE")
    parser.add_argument("--check", action="store_true", help="only report, write nothing")
    args = parser.parse_args(argv)

    site, year = Path(args.site), str(args.year)
    if args.from_json:
        export = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        url = API.format(venue=args.venue, year=year)
        with urllib.request.urlopen(url, timeout=60) as response:
            export = json.loads(response.read())
    publications = export.get("publications") or []
    papers = load_papers(site, year)
    if not papers:
        raise SystemExit(f"no data/accepted-papers-{year}.json or posters-{year}.json in {site}")

    found, problems, unmatched = {}, [], []
    video_ids = {}
    for pub in publications:
        names = [a.get("name") for a in pub.get("authors") or [] if a.get("is_presenter")]
        if pub.get("youtube_id") or names:
            pid, (score, guess) = best_paper(pub.get("title", ""), papers)
        else:
            continue
        if pid is None:
            if pub.get("paper_type") in ("regular", "poster"):
                hint = f"closest #{guess} ({score:.2f})" if guess else "no candidate"
                unmatched.append(f"{pub.get('paper_type')}: {pub.get('title', '')[:70]}  [{hint}]")
            continue
        if pub.get("youtube_id"):
            video_ids[pid] = pub["youtube_id"]
        ours = [author_name(a) for a in papers[pid].get("authors") or []]
        for name in names:
            match = [o for o in ours if same_person(o, name)]
            if len(match) == 1:
                found.setdefault(pid, [])
                if match[0] not in found[pid]:
                    found[pid].append(match[0])
            else:
                problems.append(f"#{pid}: presenter {name!r} is not (uniquely) among the authors {ours}")

    overrides_path = site / "data" / f"presenters-overrides-{year}.yml"
    overrides = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    for key, names in (overrides or {}).items():
        found[str(key)] = [str(n) for n in names]

    talks = sum(1 for p in publications if p.get("paper_type") != "poster")
    print(f"QuantumDB {args.venue}-{year}: {len(publications)} publications ({talks} talks); "
          f"presenters for {len(found)} papers"
          + (f" ({len(overrides)} from {overrides_path.name})" if overrides else ""))
    for line in problems:
        print("  ! " + line)
    for line in unmatched:
        print("  ? " + line)

    videos_path = site / "data" / f"videos-{year}.yml"
    if videos_path.exists():
        ours = (yaml.safe_load(videos_path.read_text(encoding="utf-8")) or {}).get("papers") or {}
        for pid, vid in sorted(video_ids.items(), key=lambda kv: int(kv[0])):
            mine = (ours.get(pid) or {}).get("id")
            if mine and mine != vid:
                print(f"  ~ #{pid}: videos-{year}.yml has {mine}, QuantumDB has {vid}")
            elif not mine:
                print(f"  + #{pid}: QuantumDB has a recording ({vid}) that videos-{year}.yml lacks")

    out = site / "data" / f"presenters-{year}.yml"
    lines = [f"# Generated by quantumdb_presenters.py from QuantumDB ({args.venue}-{year}, CC0).",
             f"# Corrections go in presenters-overrides-{year}.yml."]
    for pid in sorted(found, key=int):
        lines.append(f'"{pid}": [{", ".join(json.dumps(n, ensure_ascii=False) for n in found[pid])}]')
    text = "\n".join(lines) + "\n"
    if args.check:
        print(f"would write {out}")
    elif not out.exists() or out.read_text(encoding="utf-8") != text:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(f"{out} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
