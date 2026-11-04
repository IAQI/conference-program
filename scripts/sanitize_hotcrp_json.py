#!/usr/bin/env python3
"""
Turn HotCRP JSON exports into the public accepted-papers / posters data files.

    python3 sanitize_hotcrp_json.py export.json [more.json ...] -o data/accepted-papers-2026.json

Step 1 of the pipeline (see README.md). The raw exports contain e-mail
addresses, conflicts, decisions, tags and other private fields: keep them out
of the repository (e.g. in a git-ignored private_data/ folder) and only commit
the sanitized output.

What it does, per submission:
  * keeps only submissions whose decision matches --decision (if given),
    so rejected papers in a full export cannot leak into the public file;
  * records merged submissions: a HotCRP tag "merge-108-377" becomes
    "mergedwith": 377 on #108 (a list for three or more);
  * turns an "arxiv_number_url" field into options."arxiv-id";
  * --talk-type-from-decision: stores options."talk-type" (long-plenary /
    plenary / talk) derived from the decision, for QIP-style talk lists;
  * --search-arxiv: looks up submissions without an arXiv id on arXiv
    (by title and first author, one request every 3 seconds);
  * keeps only the public fields listed in PUBLIC_FIELDS / PUBLIC_AUTHOR_FIELDS
    (title, abstract, author names and affiliations, topics, ...); everything
    else is dropped, unless kept with --keep (see --list-kept-fields).
    New HotCRP fields are therefore private until someone decides otherwise.
If the export contains decisions, --decision (or --all) is required, so that
a full export never ends up public by accident.
Several input files are concatenated, e.g. the talk and the poster-only
HotCRP instances (shift the ids of the second with adjust_pids.py first).
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Allowlists: only these fields are published.
PUBLIC_FIELDS = ["object", "pid", "title", "abstract", "authors", "topics"]
PUBLIC_AUTHOR_FIELDS = ["first", "last", "affiliation", "contact"]
PUBLIC_OPTIONS = ["arxiv-id", "talk-type"]

ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")


def normalize_arxiv_id(value):
    """Return the arXiv id(s) found in a string: one id, a list of ids, or None."""
    if not isinstance(value, str):
        return None
    ids = list(dict.fromkeys(ARXIV_ID.findall(value)))
    if not ids:
        return None
    return ids if len(ids) > 1 else ids[0]


def search_arxiv(title, authors=None):
    """Find the arXiv id of a paper by title (and first author), or None."""
    query = [f'ti:"{title}"']
    if authors:
        name = f"{authors[0].get('first', '')} {authors[0].get('last', '')}".strip()
        if name:
            query.append(f'au:"{name}"')
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": " AND ".join(query), "max_results": "1"})
    try:
        time.sleep(3)  # arXiv asks for at most one request every 3 seconds
        with urllib.request.urlopen(url, timeout=15) as response:
            root = ET.fromstring(response.read())
        entry = root.find("{http://www.w3.org/2005/Atom}entry")
        if entry is not None:
            return normalize_arxiv_id(entry.findtext("{http://www.w3.org/2005/Atom}id") or "")
    except Exception as e:  # network trouble must not stop the export
        print(f"  arXiv search failed for '{title[:50]}': {e}", file=sys.stderr)
    return None


def talk_type(decision):
    d = (decision or "").lower()
    if "longplenary" in d.replace(" ", "").replace("-", ""):
        return "long-plenary"
    if "plenary" in d:
        return "plenary"
    return "talk"


def merged_with(tags, pid):
    for tag in tags or []:
        value = tag.get("tag", "") if isinstance(tag, dict) else str(tag)
        if value.startswith("merge-"):
            try:
                others = [int(p) for p in value[len("merge-"):].split("-") if int(p) != pid]
            except ValueError:
                continue
            if others:
                return others[0] if len(others) == 1 else others
    return None


def sanitize_submission(sub, args, keep):
    out = {}
    options = {k: v for k, v in (sub.get("options") or {}).items() if k in PUBLIC_OPTIONS}
    merge = merged_with(sub.get("tags"), sub.get("pid"))
    arxiv = normalize_arxiv_id(sub.get("arxiv_number_url"))
    if arxiv:
        options["arxiv-id"] = arxiv
    if args.talk_type_from_decision:
        options["talk-type"] = talk_type(sub.get("decision"))
    for key in PUBLIC_FIELDS + [k for k in keep if k not in PUBLIC_FIELDS]:
        if key not in sub:
            continue
        if key == "authors":
            out["authors"] = [{k: a[k] for k in PUBLIC_AUTHOR_FIELDS if k in a}
                              for a in sub["authors"] if isinstance(a, dict)]
        else:
            out[key] = sub[key]
    if merge is not None:
        out["mergedwith"] = merge
    if args.search_arxiv and "arxiv-id" not in options and out.get("title"):
        print(f"Searching arXiv for #{out.get('pid')}: {out['title'][:60]}")
        found = search_arxiv(out["title"], out.get("authors"))
        print(f"  {'found ' + str(found) if found else 'not found'}")
        if found:
            options["arxiv-id"] = found
    if options:
        out["options"] = options
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", metavar="EXPORT.json")
    parser.add_argument("-o", "--output", metavar="OUT.json")
    parser.add_argument("--decision", metavar="REGEX",
                        help="keep only submissions whose decision matches, e.g. 'Accept'")
    parser.add_argument("--all", action="store_true",
                        help="keep every submission even though the export has decisions")
    parser.add_argument("--keep", action="append", default=[], metavar="KEY",
                        help="also publish this top-level field (repeatable)")
    parser.add_argument("--talk-type-from-decision", action="store_true")
    parser.add_argument("--search-arxiv", action="store_true")
    parser.add_argument("--list-kept-fields", action="store_true")
    args = parser.parse_args(argv)

    if args.list_kept_fields:
        print("submission:", ", ".join(PUBLIC_FIELDS + args.keep))
        print("author:    ", ", ".join(PUBLIC_AUTHOR_FIELDS))
        print("options:   ", ", ".join(PUBLIC_OPTIONS))
        return 0
    if not args.inputs or not args.output:
        parser.error("give one or more input files and -o OUTPUT")

    submissions = []
    for path in args.inputs:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data = data if isinstance(data, list) else [data]
        print(f"{path}: {len(data)} submissions")
        submissions.extend(data)
    if not args.decision and not args.all and any(s.get("decision") for s in submissions):
        print("Error: the export contains decisions. Pass --decision REGEX (e.g. 'accept') to keep "
              "only accepted submissions, or --all to keep everything.", file=sys.stderr)
        return 1
    if args.decision:
        pattern = re.compile(args.decision, re.I)
        kept = [s for s in submissions if pattern.search(str(s.get("decision", "")))]
        print(f"decision ~ /{args.decision}/: kept {len(kept)} of {len(submissions)}")
        submissions = kept

    pids = [s.get("pid") for s in submissions]
    duplicates = sorted({p for p in pids if pids.count(p) > 1})
    if duplicates:
        print(f"Error: duplicate paper ids {duplicates}; shift one export with adjust_pids.py",
              file=sys.stderr)
        return 1

    result = [sanitize_submission(s, args, args.keep) for s in submissions]
    Path(args.output).write_text(json.dumps(result, indent=4, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    print(f"wrote {len(result)} submissions to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
