#!/usr/bin/env python3
"""
Generate the schedule of a conference year from one program spreadsheet.

    python3 generate_schedule.py --year 2026 --program program/program-2026.csv [--site .] [--check]

Step 2 of the pipeline (see README.md). The program file (CSV, e.g. exported
from a shared Google Sheet) has one row per slot of the schedule:

  day        2026-08-24
  time       14:00            start time
  end        14:20            optional; else the next slot's time is used
  session    contributed/63   optional; the session page key, i.e. the page
                              content/YEAR/sessions/<session>.md. Defaults to
                              contributed/<pid> for a slot with one paper,
                              otherwise to stuff/<title-slug>.
  title      optional for a single paper (its title is used)
  format     contributed | invited | tutorial | industry | lecture | poster | break | ...
  tags       optional, separated by spaces (used for colours on the schedule)
  location   room as displayed, e.g. "Learning Crossroads (CRX), Room 140"
  chair      optional session chair
  papers     optional paper ids, separated by spaces, commas or semicolons
  speakers   optional speaker keys (content/YEAR/speakers/**.md "key:"), separated likewise
  note       optional short note shown on the schedule card

A session that happens several times (e.g. a coffee break) is one page used
by several rows.

It writes
  data/schedule-YEAR.yml     the days and slots, read by the schedule page
  data/locations-YEAR.yml    rooms; existing entries (and descriptions) are kept
  content/YEAR/sessions/<session>.md
                             created if missing; in existing pages only the
                             keys above are updated (only when the cell is not
                             empty), everything else and the page body stay.
and reports paper ids that are unknown or not scheduled. With --check
nothing is written. Running it twice gives the same files.
"""
import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

import yaml

FIELDS = ["day", "time", "end", "session", "title", "format", "tags", "location",
          "chair", "papers", "speakers", "note"]


class Quoted(str):
    """A string always written in quotes, so that YAML never reads 08:15 or
    2026-08-24 as a number or a date."""


yaml.SafeDumper.add_representer(
    Quoted, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:str", value, style="'"))


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def split_list(cell):
    return [x for x in re.split(r"[\s,;]+", cell or "") if x]


def hhmm(value, where):
    value = (value or "").strip()
    if not value:
        return ""
    m = re.fullmatch(r"(\d{1,2})[:h.](\d{2})", value)
    if not m:
        raise SystemExit(f"{where}: cannot read time {value!r} (use HH:MM)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def read_program(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"{path}: no rows")
    missing = {"day", "time"} - set(rows[0])
    if missing:
        raise SystemExit(f"{path}: missing columns {sorted(missing)}")
    out = []
    for n, row in enumerate(rows, start=2):
        row = {k: (row.get(k) or "").strip() for k in FIELDS}
        if not row["day"] and not row["time"]:
            continue  # blank line
        where = f"{path}:{n}"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["day"]):
            raise SystemExit(f"{where}: day must be YYYY-MM-DD, got {row['day']!r}")
        row["time"], row["end"] = hhmm(row["time"], where), hhmm(row["end"], where)
        row["papers"] = [int(p.lstrip("#")) for p in split_list(row["papers"])]
        row["speakers"] = split_list(row["speakers"])
        row["tags"] = split_list(row["tags"])
        row["line"] = where
        out.append(row)
    return out


def load_front_matter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def dump_page(front, body):
    fm = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)
    body = body if body.startswith("\n") or not body else "\n" + body
    return f"---\n{fm}---\n{body}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", required=True)
    parser.add_argument("--program", required=True, help="program CSV file")
    parser.add_argument("--site", default=".", help="site root (default: current directory)")
    parser.add_argument("--check", action="store_true", help="only report, write nothing")
    args = parser.parse_args(argv)

    site, year = Path(args.site), str(args.year)
    rows = read_program(args.program)

    papers_file = site / "data" / f"accepted-papers-{year}.json"
    papers = {int(p["pid"]): p for p in json.loads(papers_file.read_text(encoding="utf-8"))} \
        if papers_file.exists() else {}
    merged_away = set()
    for p in papers.values():
        m = p.get("mergedwith")
        for other in (m if isinstance(m, list) else [m] if m is not None else []):
            merged_away.add(int(other))

    # locations: keep existing entries, add new rooms
    loc_file = site / "data" / f"locations-{year}.yml"
    locations = yaml.safe_load(loc_file.read_text(encoding="utf-8")) if loc_file.exists() else []
    locations = locations or []
    key_by_label = {l.get("label"): l["key"] for l in locations}
    for row in rows:
        label = row["location"]
        if label and label not in key_by_label:
            key = slugify(label) or "room"
            while key in {l["key"] for l in locations}:
                key += "-2"
            locations.append({"key": key, "label": label})
            key_by_label[label] = key

    # sessions: one page per key, set from the first row that names it
    problems = []
    sessions = OrderedDict()
    for row in rows:
        if not row["session"]:
            if len(row["papers"]) == 1 and not row["title"]:
                row["session"] = f"contributed/{row['papers'][0]}"
            elif row["title"]:
                row["session"] = f"stuff/{slugify(row['title'])}"
            else:
                problems.append(f"{row['line']}: no session, title or paper")
                continue
        for pid in row["papers"]:
            if papers and pid not in papers:
                problems.append(f"{row['line']}: paper #{pid} is not in {papers_file.name}")
        if row["session"] not in sessions:
            sessions[row["session"]] = row

    # schedule: days in order of appearance, slots in order of the file
    days = OrderedDict()
    for row in rows:
        if not row["session"]:
            continue
        slot = {"session": row["session"], "time": Quoted(row["time"])}
        if row["end"]:
            slot["end"] = Quoted(row["end"])
        if row["location"]:
            slot["location"] = key_by_label[row["location"]]
        days.setdefault(row["day"], []).append(slot)
    schedule = [{"day": Quoted(d), "sessions": slots} for d, slots in days.items()]

    scheduled = {pid for row in rows for pid in row["papers"]}
    for pid in sorted(set(papers) - scheduled - merged_away):
        problems.append(f"paper #{pid} ({papers[pid].get('title', '')[:60]}) is not scheduled")

    # session pages
    pages = []
    for key, row in sessions.items():
        path = site / "content" / year / "sessions" / f"{key}.md"
        front, body = load_front_matter(path) if path.exists() else ({}, "")
        # an explicit title wins; otherwise keep the page's title, or derive one
        title = row["title"] or front.get("title")
        if not title and len(row["papers"]) == 1 and row["papers"][0] in papers:
            title = papers[row["papers"][0]]["title"]
        updates = OrderedDict([
            ("title", title or key),
            ("format", row["format"]),
            ("type", "sessions"),
            ("year", int(year)),
            ("tags", row["tags"]),
            ("chair", row["chair"]),
            ("papers", row["papers"]),
            ("speakers", row["speakers"]),
            ("note", row["note"]),
        ])
        new = dict(front)
        for k, v in updates.items():
            if v not in ("", [], None):
                new[k] = v
        new.setdefault("draft", False)
        if path.exists() and new == front:
            continue  # nothing changed: leave the hand-written file as it is
        pages.append((path, dump_page(new, body)))

    outputs = [
        (site / "data" / f"schedule-{year}.yml",
         "# Generated by generate_schedule.py from " + Path(args.program).name + "; edit that file instead.\n"
         + yaml.safe_dump(schedule, sort_keys=False, allow_unicode=True, width=1000)),
        (loc_file, yaml.safe_dump(locations, sort_keys=False, allow_unicode=True, width=1000)),
    ]
    changed = [(p, t) for p, t in outputs if not p.exists() or p.read_text(encoding="utf-8") != t] + pages

    print(f"{len(rows)} slots on {len(days)} days, {len(sessions)} sessions, "
          f"{len(scheduled)} papers, {len(locations)} rooms")
    for p in problems:
        print("  ! " + p)
    for path, text in changed:
        print(("would write " if args.check else "wrote ") + str(path.relative_to(site)))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if not changed:
        print("everything up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
