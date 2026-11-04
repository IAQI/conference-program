#!/usr/bin/env python3
"""
Derive the list of presenting authors from the registration spreadsheet.

The registration exports list, for each registered person, whether they present a
talk or a poster and the title of it. They arrive in whatever shape the organisers
have to hand -- one spreadsheet per presentation type at first, later a combined
csv of everyone registered so far -- so this script reads them all, sorts their
rows by the kind each declares, matches those titles against the matching
accepted-submission data and writes the union to a `presenters-<year>.yml` data
file mapping each paper id to the name(s) of its presenting author(s), so that
Hugo can render them in bold.

Later exports repeat rows from earlier ones, and sometimes rows of their own, so
identical declarations are read once. Counting a person twice would not merely be
redundant: it defeats the elimination that decides which of several talks someone
actually presents.

Matching is title-first and deliberately conservative: a registrant is only
attached to a paper when their declared title identifies that paper, and their
name is then used solely to pick which author of *that* paper to mark. Rows that
cannot be resolved are reported for human review rather than guessed at, which is
what keeps invited speakers, and people registered for another kind of
presentation, out of the result even when they happen to co-author a submission.

Usage (step 3 of the pipeline, see README.md):

    python3 mark_presenters.py --year 2026 --registrations private_data/reg1.xlsx private_data/reg2.csv

The registration form needs the questions "Will you be presenting?" (talk /
poster / both / no) and "Title of presentation", next to first and last name.
Keep the exports out of git (they hold personal data). Without
--registrations only data/presenters-overrides-YEAR.yml is used, which is the
way to go when presenters are known from elsewhere (e.g. the session chairs).
"""

import argparse
import csv
import difflib
import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import yaml

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Substring matching is only trusted once *both* strings are at least this long.
# Bounding only the paper title would let a stub cell such as "N/A" fold to "na"
# and be found inside dozens of unrelated titles.
MIN_SUBSTRING_LEN = 20

# Similarity above which two normalized titles are considered the same paper.
TITLE_SIMILARITY_THRESHOLD = 0.85

# Similarity below which a failed match is not even worth reporting as a near
# miss; between this and the threshold above, the candidate is shown to a human.
TITLE_NEAR_MISS_THRESHOLD = 0.5

# Each presentation kind, the values its registrants pick in the "will you be
# presenting" column, and the accepted-submission file whose titles they declare.
# Every kind is matched only against its own submissions and only against the
# rows that declare it, so a poster title can never be fuzzy-matched to a
# similarly named talk, and the results are merged into one presenters file.
SOURCES = [
    ("talks", {"oral", "both"}, "accepted-papers-{year}.json"),
    ("posters", {"poster", "both"}, "posters-{year}.json"),
]


# Characters that transliterate to more than one ASCII letter, and so are not
# handled by accent stripping alone ("Möbus" is spelled "Moebus" elsewhere).
TRANSLITERATIONS = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "ß": "ss", "æ": "ae", "ø": "oe", "å": "aa",
}


def read_xlsx_rows(path):
    """
    Read the first worksheet of an .xlsx file as a list of column->value dicts.

    Args:
        path (Path): Path to the .xlsx workbook.

    Returns:
        list: One dict per row, keyed by column letter (e.g. {"A": "Uma", ...}).
    """
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        # Exports vary: shared strings are optional, and the worksheet is not
        # always called sheet1.xml.
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [
                "".join(node.text or "" for node in item.iter(NS + "t"))
                for item in ElementTree.fromstring(
                    archive.read("xl/sharedStrings.xml")
                ).iter(NS + "si")
            ]
        worksheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
        if not worksheets:
            raise ValueError(f"{path}: contains no worksheet")
        sheet = ElementTree.fromstring(archive.read(worksheets[0]))

    rows = []
    for row in sheet.iter(NS + "row"):
        cells = {}
        for cell in row.iter(NS + "c"):
            column = re.match(r"[A-Z]+", cell.get("r")).group()
            value = cell.find(NS + "v")
            inline = cell.find(NS + "is")
            if cell.get("t") == "s" and value is not None:
                text = shared[int(value.text)]
            elif inline is not None:
                text = "".join(node.text or "" for node in inline.iter(NS + "t"))
            else:
                text = value.text if value is not None else ""
            cells[column] = (text or "").strip()
        rows.append(cells)
    return rows


def read_csv_rows(path):
    """
    Read a .csv export as a list of column->value dicts, shaped like read_xlsx_rows.

    The organisers' exports are not consistently encoded or delimited -- the
    registration system emits cp1252 with semicolons where the spreadsheets it
    exports from use UTF-8 with commas -- so both are sniffed rather than assumed.

    Args:
        path (Path): Path to the .csv file.

    Returns:
        list: One dict per row, keyed by spreadsheet column letter.
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: is neither UTF-8 nor cp1252")

    # Sniffing on the header alone: a title cell may well contain the delimiter
    # that was not chosen, which is exactly what confuses csv.Sniffer.
    header = text.splitlines()[0] if text.splitlines() else ""
    delimiter = max(";,\t", key=header.count)

    rows = []
    for record in csv.reader(io.StringIO(text), delimiter=delimiter):
        rows.append({
            # Column 27 onwards would need a two-letter name, and no registration
            # export comes close, so refuse rather than mislabel one.
            chr(ord("A") + index): (value or "").strip()
            for index, value in enumerate(record)
            if index < 26
        })
    return rows


def read_rows(path):
    """
    Read a registration export, whether it arrived as a spreadsheet or a csv.

    Args:
        path (Path): Path to the export.

    Returns:
        list: One dict per row, keyed by spreadsheet column letter.
    """
    if Path(path).suffix.lower() == ".csv":
        return read_csv_rows(path)
    return read_xlsx_rows(path)


def parse_registrations(rows):
    """
    Extract the registrant records that sit below the spreadsheet's header row.

    Args:
        rows (list): Rows as returned by read_xlsx_rows.

    Returns:
        list: Dicts with "first", "last", "kind" and "titles" keys.

    Raises:
        ValueError: If no header row can be located.
    """
    header_index = None
    for index, row in enumerate(rows):
        values = [value.lower() for value in row.values()]
        if any(v.startswith("first name") for v in values) and any(
            v.startswith("last name") for v in values
        ):
            header_index = index
            break
    if header_index is None:
        raise ValueError("could not find the 'First name'/'Last name' header row")

    columns = {}
    for column, value in rows[header_index].items():
        value = value.lower()
        if value.startswith("first name"):
            columns["first"] = column
        elif value.startswith("last name"):
            columns["last"] = column
        elif value.startswith("will you be presenting"):
            columns["kind"] = column
        elif value.startswith("title of presentation"):
            columns["titles"] = column

    # Falling back to a fixed column letter here would silently read whatever
    # happens to sit in that position -- affiliations, say -- as talk titles, and
    # match nothing while reporting success.
    missing = [name for name in ("first", "last", "titles") if name not in columns]
    if missing:
        raise ValueError(
            f"missing expected column(s) {', '.join(missing)} in the header row: "
            f"{sorted(rows[header_index].values())}"
        )

    registrations = []
    for row in rows[header_index + 1:]:
        first = row.get(columns["first"], "")
        last = row.get(columns["last"], "")
        if not first and not last:
            continue
        registrations.append({
            "first": first,
            "last": last,
            # None, not "", when the export has no such column at all: a sheet
            # that never says what its rows present must not be filtered on it.
            "kind": row.get(columns["kind"], "") if "kind" in columns else None,
            "titles": row.get(columns["titles"], ""),
        })
    return registrations


def select_kind(registrations, wanted):
    """
    Keep the registrations that declare one of the presentation kinds wanted.

    The organisers send both one sheet per kind and, later, a single combined
    list of everyone who registered since. Filtering on the declared kind is what
    lets the two be read the same way, and it keeps a poster title from being
    fuzzy-matched against a similarly named talk.

    A row is filtered only on what it actually declares. One that says nothing --
    because the export has no such column, or because it was left blank -- is
    offered to every kind instead of being dropped, so that a presenter is never
    lost silently. It then either matches a submission or is reported for review.

    Args:
        registrations (list): Records as returned by parse_registrations.
        wanted (set): Declared kinds to keep, lowercased.

    Returns:
        list: The matching records, plus any that declare no kind at all.
    """
    return [
        registration for registration in registrations
        if not (registration["kind"] or "").strip()
        or registration["kind"].strip().lower() in wanted
    ]


def dedupe(registrations):
    """
    Drop repeated registrations, keeping the first of each.

    The organisers' combined list is not only the people who registered since the
    last one: it repeats most of the earlier sheet, and a handful of its own rows
    twice. Reading one person twice would be worse than merely redundant, because
    settle_candidates commits the first copy to the one talk left unclaimed and
    then finds the second copy has nothing left, which strands it on every talk
    it named -- the opposite of the narrowing that was wanted.

    Args:
        registrations (list): Records as returned by parse_registrations.

    Returns:
        list: The records, in order, with later repeats of a person's identical
            declaration removed.
    """
    unique = []
    seen = set()
    for registration in registrations:
        key = (
            fold(f"{registration['first']} {registration['last']}"),
            fold(registration["titles"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(registration)
    return unique


def fold(text):
    """
    Reduce text to bare lowercase ASCII letters and digits for comparison.

    Args:
        text (str): Arbitrary text.

    Returns:
        str: Folded text, with accents removed and punctuation dropped.
    """
    for source, target in TRANSLITERATIONS.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_variants(first, last):
    """
    Build the set of folded spellings under which a person may appear.

    Accepted-paper author lists and the registration sheet disagree about middle
    names, initials and multi-token surnames, so a person matches if any variant
    of one spelling coincides with any variant of the other.

    Args:
        first (str): Given name, possibly including middle names or initials.
        last (str): Family name, possibly made of several tokens.

    Returns:
        set: Folded name spellings.
    """
    first_tokens = [token for token in (fold(t) for t in first.split()) if token]
    last_tokens = [token for token in (fold(t) for t in last.split()) if token]
    folded_first = "".join(first_tokens)
    folded_last = "".join(last_tokens)

    variants = {folded_first + folded_last}
    if first_tokens:
        variants.add(first_tokens[0] + folded_last)
    if last_tokens:
        variants.add(folded_first + last_tokens[-1])
    if first_tokens and last_tokens:
        variants.add(first_tokens[0] + last_tokens[-1])
    return {variant for variant in variants if variant}


def closest_paper(folded, papers):
    """
    Find the paper whose folded title is most similar to the given text.

    Args:
        folded (str): Folded text to look up.
        papers (list): Accepted-paper records.

    Returns:
        tuple: (paper, ratio), or (None, 0.0) if there are no papers.
    """
    best = None
    best_ratio = 0.0
    for paper in papers:
        ratio = difflib.SequenceMatcher(None, folded, fold(paper["title"])).ratio()
        if ratio > best_ratio:
            best, best_ratio = paper, ratio
    return best, best_ratio


def match_papers(cell, papers):
    """
    Find every paper identified by a registrant's declared title(s).

    A single cell may name several talks, so every paper whose folded title is
    contained in the folded cell matches. Containment also absorbs suffixes the
    organisers appended to a title after acceptance, and a fuzzy fallback absorbs
    spelling drift between the sheet and the submission.

    Whatever the matched titles do not account for is fed back through the fuzzy
    matcher and surfaced as a note, so that a cell naming two talks of which only
    one is recognised cannot lose the second one silently.

    Args:
        cell (str): The raw "Title of presentation or poster" cell.
        papers (list): Accepted-paper records.

    Returns:
        tuple: (matches, notes), where notes explains anything left unaccounted
            for, for human review.
    """
    folded_cell = fold(cell)
    if len(folded_cell) < MIN_SUBSTRING_LEN:
        return [], ["declared title is too short to identify a paper"]

    matches = []
    for paper in papers:
        folded_title = fold(paper["title"])
        if len(folded_title) < MIN_SUBSTRING_LEN:
            continue
        if folded_title in folded_cell or folded_cell in folded_title:
            matches.append(paper)

    if matches:
        # Only titles found *inside* the cell consume part of it; a cell that is
        # itself a fragment of one title accounts for the whole cell.
        residual = folded_cell
        for paper in matches:
            residual = residual.replace(fold(paper["title"]), "", 1)
        if residual == folded_cell:
            residual = ""
        if len(residual) < MIN_SUBSTRING_LEN:
            return matches, []
        near, ratio = closest_paper(residual, papers)
        note = (
            f"names {len(matches)} known paper(s) but {len(residual)} characters "
            f"are unaccounted for"
        )
        if near is not None and ratio >= TITLE_NEAR_MISS_THRESHOLD:
            note += f"; closest unmatched paper is #{near['pid']} {near['title']!r} ({ratio:.2f})"
        return matches, [note]

    best, ratio = closest_paper(folded_cell, papers)
    if ratio >= TITLE_SIMILARITY_THRESHOLD:
        return [best], []
    if best is not None and ratio >= TITLE_NEAR_MISS_THRESHOLD:
        return [], [
            f"no accepted paper has this title; closest is #{best['pid']} "
            f"{best['title']!r} ({ratio:.2f}, below the {TITLE_SIMILARITY_THRESHOLD} threshold)"
        ]
    return [], ["no accepted paper has this title"]


def find_author(paper, registration):
    """
    Locate the registrant among a paper's authors.

    Args:
        paper (dict): An accepted-paper record.
        registration (dict): A registrant record.

    Returns:
        dict or None: The matching author record, or None if absent.
    """
    wanted = name_variants(registration["first"], registration["last"])
    for author in paper["authors"]:
        if wanted & name_variants(author["first"], author["last"]):
            return author
    return None


def settle_candidates(candidates):
    """
    Narrow registrants who name several talks down to the ones they must give.

    Someone whose cell names a single talk is committed to it, which settles that
    talk. A registrant naming several talks then need not cover a talk another
    registrant is already committed to, and dropping it may in turn commit them
    to what is left. Iterating that to a fixpoint resolves, for example, one
    author naming two of their papers while a co-author of the second names only
    that one: the co-author is committed, so the first presents the other.

    A talk may still end up with several presenters when each of them named only
    it, and a registrant who names several talks that nobody else claims keeps
    all of them.

    Args:
        candidates (list): One list of candidate paper ids per registrant, in
            registrant order.

    Returns:
        tuple: (settled, decisions, stranded), where settled holds the retained
            paper ids per registrant, decisions describes each narrowing that
            occurred, and stranded lists registrants every one of whose talks is
            spoken for by someone else.
    """
    settled = [list(pids) for pids in candidates]
    decisions = []
    stranded = []
    committed = {index for index, pids in enumerate(settled) if len(pids) == 1}
    claimed = {settled[index][0] for index in committed}

    narrowing = True
    while narrowing:
        narrowing = False
        for index, pids in enumerate(settled):
            if index in committed or len(pids) <= 1:
                continue
            remaining = [pid for pid in pids if pid not in claimed]
            if not remaining:
                # Every talk they named is spoken for. Eliminating further would
                # leave them presenting nothing, so keep the cell as it stands
                # and let a human decide.
                if index not in stranded:
                    stranded.append(index)
                continue
            if len(remaining) == len(pids):
                continue
            decisions.append((index, list(pids), list(remaining)))
            settled[index] = remaining
            narrowing = True
            if len(remaining) == 1:
                committed.add(index)
                claimed.add(remaining[0])
    return settled, decisions, stranded


def resolve(registrations, papers):
    """
    Assign each registrant to the paper they present.

    Args:
        registrations (list): Registrant records.
        papers (list): Accepted-paper records.

    Returns:
        tuple: (assignments, problems, decisions), where assignments maps paper
            id to an ordered list of presenting author names, problems is a list
            of (registrant name, declared title, reason) triples for human
            review, and decisions describes the narrowings settle_candidates
            made.
    """
    problems = []
    per_registrant = []
    for registration in registrations:
        who = f"{registration['first']} {registration['last']}".strip()
        matched, notes = match_papers(registration["titles"], papers)
        for note in notes:
            problems.append((who, registration["titles"], note))

        usable = []
        for paper in matched:
            author = find_author(paper, registration)
            if author is None:
                problems.append((
                    who,
                    registration["titles"],
                    f"matched paper #{paper['pid']} but is not among its authors",
                ))
                continue
            usable.append((int(paper["pid"]), f"{author['first']} {author['last']}"))
        per_registrant.append((who, usable))

    settled, narrowings, stranded = settle_candidates(
        [[pid for pid, _ in usable] for _, usable in per_registrant]
    )
    for index in stranded:
        who = per_registrant[index][0]
        named = ", ".join(f"#{pid}" for pid in settled[index])
        problems.append((
            who,
            registrations[index]["titles"],
            f"names only talks ({named}) that others registered to present; "
            f"left on all of them",
        ))

    assignments = {}
    for (who, usable), keep in zip(per_registrant, settled):
        for pid, name in usable:
            if pid not in keep:
                continue
            names = assignments.setdefault(pid, [])
            if name not in names:
                names.append(name)

    decisions = [
        (per_registrant[index][0], before, after)
        for index, before, after in narrowings
    ]
    return assignments, problems, decisions


def load_overrides(path):
    """
    Load the hand-maintained overrides file, if one exists.

    The generated file is never read back: re-deriving it wholly from the sheet
    is what stops a registrant who has since withdrawn from being preserved for
    ever. Decisions a human makes instead live here, and this file is only ever
    read, never written.

    An entry replaces whatever the sheet produced for that paper, so it can add,
    correct or (with an empty list) suppress a bolding.

    Args:
        path (Path): Path to the overrides file.

    Returns:
        dict: Paper id to list of names, keyed by int. Empty if absent.

    Raises:
        ValueError: If the file is not a mapping of paper id to a list of names.
    """
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping of paper id to author names")

    overrides = {}
    for pid, names in loaded.items():
        # A bare string would otherwise be accepted and iterated character by
        # character, and Hugo would then match author names as substrings of it.
        if isinstance(names, str) or not isinstance(names, (list, tuple)):
            raise ValueError(
                f"{path}: entry \"{pid}\" must be a list of names, got {names!r}. "
                f"Write it as [\"{names}\"] if you meant a single presenter."
            )
        try:
            key = int(pid)
        except (TypeError, ValueError):
            raise ValueError(f"{path}: \"{pid}\" is not a paper id") from None
        overrides[key] = [str(name) for name in names]
    return overrides


def write_presenters(path, assignments, year, sheets):
    """
    Write the presenters data file with string keys sorted by paper id.

    Args:
        path (Path): Destination path.
        assignments (dict): Paper id to list of presenting author names.
        year (str): Conference year, used in the file header.
        sheets (list): Spreadsheets the assignments were derived from.
    """
    lines = [
        f"# Presenting authors for {year}, rendered in bold in the author lists.",
        "#",
        "# Generated by scripts/mark_presenters.py from:",
    ]
    lines += [f"#   {sheet.as_posix()}" for sheet in sheets]
    lines += [
        f"# Do not hand-edit: re-running the script rewrites this file from those",
        f"# spreadsheets. Put manual decisions in presenters-overrides-{year}.yml instead.",
    ]
    for pid in sorted(assignments):
        names = ", ".join(json.dumps(name, ensure_ascii=False) for name in assignments[pid])
        lines.append(f'"{pid}": [{names}]')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", required=True, help="conference year")
    parser.add_argument(
        "--registrations",
        type=Path,
        nargs="+",
        default=[],
        help="registration exports (.xlsx or .csv), each read for every presentation "
             "kind. Later exports may repeat earlier ones: pass them all.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="directory holding the Hugo data files (default: data)",
    )
    args = parser.parse_args()

    sheets = args.registrations
    missing = [sheet for sheet in sheets if not sheet.is_file()]
    if missing:
        parser.error(
            "no such registration export: "
            f"{', '.join(sheet.as_posix() for sheet in missing)}"
        )

    output_path = args.data_dir / f"presenters-{args.year}.yml"
    overrides_path = args.data_dir / f"presenters-overrides-{args.year}.yml"

    assignments = {}
    problems = []
    decisions = []
    tallies = []
    claimed_by = {}
    for kind, declared, papers_name in SOURCES:
        papers_path = args.data_dir / papers_name.format(year=args.year)
        if not papers_path.is_file():
            print(f"note: no {papers_path}, skipping {kind}")
            continue
        papers = json.loads(papers_path.read_text(encoding="utf-8"))

        # One presenters file can only be keyed by paper id if the ids mean the
        # same submission everywhere. They come from a single HotCRP today, but
        # a list rebuilt with its own numbering would silently bold the wrong
        # authors, so say so loudly instead.
        clashes = sorted(int(paper["pid"]) for paper in papers if int(paper["pid"]) in claimed_by)
        if clashes:
            print(
                f"error: {papers_path} reuses paper id(s) "
                f"{', '.join(f'#{pid}' for pid in clashes[:10])} already used by the "
                f"{claimed_by[clashes[0]]}; they cannot share one presenters file",
                file=sys.stderr,
            )
            return 1
        claimed_by.update({int(paper["pid"]): kind for paper in papers})

        registrations = []
        for sheet in sheets:
            registrations += select_kind(parse_registrations(read_rows(sheet)), declared)
        registrations = dedupe(registrations)
        found, issues, narrowings = resolve(registrations, papers)
        assignments.update(found)
        problems += [(kind, *issue) for issue in issues]
        decisions += [(kind, *narrowing) for narrowing in narrowings]
        tallies.append((kind, sheets, papers_path, len(registrations), len(papers), len(found)))

    # Checked before the overrides are merged in: they are a handful of hand-written
    # entries, and letting them stand in for a run that matched nothing would turn a
    # moved spreadsheet into a near-empty file written over the good one.
    if sheets and not assignments:
        total = sum(tally[3] for tally in tallies)
        print(
            f"error: matched no presenter at all from {total} registration(s); "
            f"refusing to write an empty {output_path}",
            file=sys.stderr,
        )
        return 1

    overrides = load_overrides(overrides_path)
    assignments.update(overrides)
    if not assignments:
        print(f"error: no --registrations given and no entries in {overrides_path}; "
              f"nothing to write", file=sys.stderr)
        return 1

    write_presenters(output_path, assignments, args.year, sheets)

    presenters = sum(len(names) for names in assignments.values())
    for kind, from_sheets, papers_path, registered, accepted, found in tallies:
        named = ", ".join(sheet.as_posix() for sheet in from_sheets)
        print(f"{kind:<8}: {registered} registration(s) from {named}")
        print(f"{'':<8}  {accepted} accepted from {papers_path} -> {found} with a presenter")
    if overrides:
        print(f"manual overrides: {len(overrides)} (from {overrides_path})")
    print(f"papers with a presenter: {len(assignments)} ({presenters} presenters)")
    print(f"wrote {output_path}")

    if decisions:
        print("\nnarrowed by elimination:")
        for kind, who, before, after in decisions:
            dropped = ", ".join(f"#{pid}" for pid in before if pid not in after)
            kept = ", ".join(f"#{pid}" for pid in after)
            print(f"  [{kind}] {who}: named {len(before)} titles, {dropped} claimed by "
                  f"someone who named only that one -> presents {kept}")

    if problems:
        print(f"\n{len(problems)} registration(s) need a human decision.", file=sys.stderr)
        print(
            f"Invited speakers, and people whose presentation is not in the accepted\n"
            f"list, are expected here. For anything else, add an entry to\n"
            f"{overrides_path}:\n",
            file=sys.stderr,
        )
        for kind, who, title, reason in problems:
            print(f"  [{kind}] {who}", file=sys.stderr)
            print(f"    declared: {title}", file=sys.stderr)
            print(f"    reason  : {reason}\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
