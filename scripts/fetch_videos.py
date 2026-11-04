#!/usr/bin/env python3
"""
Link the talk recordings on YouTube to the papers and sessions of a year.

    python3 fetch_videos.py --year 2026 --playlist URL [--playlist URL ...] [--site .] [--check]

Step 4 of the pipeline (see README.md). Lists the videos of one or more
YouTube playlists (with yt-dlp, which must be installed), matches each video
title against

  * the titles in data/accepted-papers-YEAR.json      -> papers:   {"<pid>": ...}
  * the titles of content/YEAR/sessions/**.md pages    -> sessions: {"<key>": ...}
    (invited talks, tutorials, panels; prefixes like "Invited Talk:" are ignored)

and writes data/videos-YEAR.yml, which the templates use to link videos from
the schedule, the session pages and the accepted papers list:

    papers:
      "63": {id: MHJcaaysIN0, title: "On Removing Interaction ..."}
    sessions:
      invited/Goldin: {id: dCibf89nwI8, title: "Invited Talk: ..."}

Titles of the form "Speaker Name: Paper title" (as on the QIP channel) are
understood, and the speaker is stored as `presenter`.

Matching is conservative: a video is only linked when its title is at least
--threshold similar (default 0.85) to exactly one paper or session. Everything
else is listed for a human. Fix or add matches by hand in
data/videos-overrides-YEAR.yml (same layout; an entry `"63": null` removes a
match); they win over the automatic ones on every run.

--from-json FILE reads `yt-dlp --flat-playlist -J URL` output instead of
calling yt-dlp (handy offline and for tests).
"""
import argparse
import difflib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

PREFIX = re.compile(
    r"^\s*(?:(?:invited|tutorial|contributed|plenary|keynote|industry|public|award|best\s+\w+\s+paper)"
    r"(?:\s+(?:talk|lecture|session|panel))?\s*[:\-–|]\s*)+", re.I)
PREFIX_NO_SEP = re.compile(   # "INVITED TALK John Watrous: ..."
    r"^\s*(?:invited|plenary|tutorial|contributed|keynote)\s+(?:talk|lecture|session)\s+", re.I)
PID_TAG = re.compile(r"^\s*#\d+(?:\s*/\s*#?\d+)*\s*")
TRAILER = re.compile(r"\s*[|–\-]\s*(?:qcrypt|tqc|qip)\s*\d{4}.*$", re.I)


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


BRACKET_TAG = re.compile(r"^\s*\[[^\]]*\]\s*")          # "[QCrypt2025] ..."
PAREN_LABEL = re.compile(r"(^|:\s*)\((?:public lecture|invited talk|tutorial|keynote|panel)\)\s*", re.I)


def clean_title(title):
    title = BRACKET_TAG.sub("", title or "")
    title = TRAILER.sub("", title)
    title = PAREN_LABEL.sub(r"\1", title)
    title = PREFIX.sub("", title)
    title = PREFIX_NO_SEP.sub("", title)
    return PID_TAG.sub("", title).strip()


def looks_like_name(text):
    words = text.split()
    return 1 < len(words) <= 5 and all(w[:1].isupper() for w in words if w[:1].isalpha()) \
        and not any(w.lower() in {"on", "of", "the", "and", "for", "in", "with", "a"} for w in words)


def variants(video_title):
    """(title to match, presenter) readings of a video title."""
    base = clean_title(video_title)
    out = [(base, None)]
    if ":" in base:
        left, right = (x.strip() for x in base.split(":", 1))
        speakers = [s.strip() for s in re.split(r"\s*[&|,]\s*|\s+and\s+", left)]
        if all(looks_like_name(s) for s in speakers):  # "Speaker Name: Title", "A & B: Title"
            out.append((right, left))
        left, right = (x.strip() for x in base.rsplit(":", 1))
        names = [n.strip() for n in re.split(r",|\band\b", right.rstrip(" .…")) if n.strip()]
        if names and all(looks_like_name(n) or len(n.split()) <= 3 for n in names):
            # "Title: Author, Author, ..." (the first author is not necessarily the speaker)
            out.append((left, names[0] if len(names) == 1 else None))
    return out


def similarity(video, target):
    a, b = normalize(video), normalize(target)
    if not a or not b:
        return 0.0
    if video.rstrip().endswith(("...", "…")):  # truncated by YouTube or the uploader
        a = normalize(video.rstrip(" .…"))
        b = b[:len(a)]
    return difflib.SequenceMatcher(None, a, b).ratio()


def front_matter(path):
    m = re.match(r"---\s*\n(.*?)\n---", path.read_text(encoding="utf-8"), re.S)
    return (yaml.safe_load(m.group(1)) if m else None) or {}


def load_speaker_names(site, year):
    """Map speaker keys to the names that may appear in a video title."""
    names = {}
    speakers_dir = site / "content" / year / "speakers"
    for page in speakers_dir.rglob("*.md") if speakers_dir.exists() else []:
        front = front_matter(page)
        if front.get("key") and front.get("name"):
            names[str(front["key"])] = str(front["name"])
    return names


def load_sessions_by_speaker(site, year):
    """(session key, [speaker names]) for sessions that list speakers."""
    out = []
    known = load_speaker_names(site, year)
    sessions_dir = site / "content" / year / "sessions"
    for page in sorted(sessions_dir.rglob("*.md")) if sessions_dir.exists() else []:
        speakers = front_matter(page).get("speakers") or []
        if speakers and not page.name.startswith("_"):
            names = [known.get(str(k), str(k).replace("_", " ").replace("-", " ")) for k in speakers]
            out.append((page.relative_to(sessions_dir).with_suffix("").as_posix(), names))
    return out


def match_by_speaker(video_title, sessions_by_speaker):
    """The one session whose speaker's name appears in the video title, or None."""
    title = f" {normalize(video_title)} "
    hits = [key for key, names in sessions_by_speaker
            if any(f" {normalize(n)} " in title for n in names if normalize(n))]
    return hits[0] if len(set(hits)) == 1 else None


def load_targets(site, year):
    targets = []  # (kind, key, title)
    papers_file = site / "data" / f"accepted-papers-{year}.json"
    if papers_file.exists():
        for p in json.loads(papers_file.read_text(encoding="utf-8")):
            targets.append(("papers", str(int(p["pid"])), p.get("title", "")))
    sessions_dir = site / "content" / year / "sessions"
    for page in sorted(sessions_dir.rglob("*.md")) if sessions_dir.exists() else []:
        if page.name.startswith("_"):
            continue
        m = re.match(r"---\s*\n(.*?)\n---", page.read_text(encoding="utf-8"), re.S)
        front = yaml.safe_load(m.group(1)) if m else {}
        title = clean_title((front or {}).get("title", ""))
        key = page.relative_to(sessions_dir).with_suffix("").as_posix()
        if title:
            targets.append(("sessions", key, title))
    return targets


def list_playlist(url):
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "-J", url], check=True,
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise SystemExit("yt-dlp is not installed (pip install yt-dlp, or brew install yt-dlp)")
    return json.loads(out)


def match(videos, targets, threshold, sessions_by_speaker=()):
    found, unmatched = {}, []
    for v in videos:
        scored = [(similarity(t, target), kind) for t, _ in variants(v["title"])
                  for kind, _, target in targets]
        if not any(s >= threshold for s, _ in scored):
            # no title matches: an invited talk or tutorial titled by its speaker?
            key = match_by_speaker(v["title"], sessions_by_speaker)
            if key and ("sessions", key) not in found:
                found[("sessions", key)] = {"id": v["id"], "title": v["title"]}
                continue
        scored = []
        for title, presenter in variants(v["title"]):
            for kind, key, target in targets:
                scored.append((similarity(title, target), kind, key, presenter))
        scored.sort(key=lambda s: -s[0])
        best = scored[0] if scored else (0, None, None, None)
        # a session titled exactly like its single paper: prefer the paper
        rivals = [s for s in scored[1:] if s[0] >= threshold and (s[1], s[2]) != (best[1], best[2])
                  and not (s[0] == best[0] and best[1] == "papers")]
        if best[0] >= threshold and not (rivals and rivals[0][0] >= best[0] - 0.02 and rivals[0][1] == best[1]):
            entry = {"id": v["id"], "title": v["title"]}
            if best[3]:
                entry["presenter"] = best[3]
            previous = found.get((best[1], best[2]))
            if previous:
                unmatched.append((v, f"also matches {best[1]} {best[2]}, already linked to {previous['id']}"))
                continue
            found[(best[1], best[2])] = entry
        else:
            hint = f"best guess {best[1]} {best[2]} ({best[0]:.2f})" if best[1] else "no candidate"
            unmatched.append((v, hint))
    return found, unmatched


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", required=True)
    parser.add_argument("--playlist", action="append", default=[], metavar="URL")
    parser.add_argument("--from-json", action="append", default=[], metavar="FILE")
    parser.add_argument("--site", default=".")
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--check", action="store_true", help="only report, write nothing")
    args = parser.parse_args(argv)
    if not args.playlist and not args.from_json:
        parser.error("give at least one --playlist (or --from-json)")

    site, year = Path(args.site), str(args.year)
    playlists = [list_playlist(u) for u in args.playlist] + \
                [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.from_json]
    videos, seen = [], set()
    for pl in playlists:
        for e in pl.get("entries") or []:
            title = e.get("title") or ""
            if e.get("id") and e["id"] not in seen and title not in ("", "[Private video]", "[Deleted video]"):
                seen.add(e["id"])
                videos.append({"id": e["id"], "title": title})
    targets = load_targets(site, year)
    found, unmatched = match(videos, targets, args.threshold, load_sessions_by_speaker(site, year))

    result = {"papers": {}, "sessions": {}}
    for (kind, key), entry in found.items():
        result[kind][key] = entry
    overrides_file = site / "data" / f"videos-overrides-{year}.yml"
    overrides = yaml.safe_load(overrides_file.read_text(encoding="utf-8")) if overrides_file.exists() else {}
    for kind in ("papers", "sessions"):
        for key, entry in ((overrides or {}).get(kind) or {}).items():
            key = str(key)
            if entry is None:
                result[kind].pop(key, None)
            else:
                result[kind][key] = entry
    overridden = {e.get("id") for kind in ("papers", "sessions")
                  for e in ((overrides or {}).get(kind) or {}).values() if e}
    unmatched = [(v, why) for v, why in unmatched if v["id"] not in overridden]
    for kind in result:
        result[kind] = dict(sorted(result[kind].items(),
                                   key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0])))

    print(f"{len(videos)} videos: {len(result['papers'])} papers and "
          f"{len(result['sessions'])} sessions linked, {len(unmatched)} not linked")
    for v, why in unmatched:
        print(f"  ? {v['id']}  {v['title'][:70]}  [{why}]")
    paper_keys = {k for kind, k, _ in targets if kind == "papers"}
    missing = sorted(paper_keys - set(result["papers"]), key=int)
    if missing:
        print(f"  papers without a video: {', '.join('#' + k for k in missing)}")

    out = site / "data" / f"videos-{year}.yml"
    text = (f"# Generated by fetch_videos.py; corrections go in {overrides_file.name}.\n"
            + yaml.safe_dump(result, sort_keys=False, allow_unicode=True, width=1000))
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
