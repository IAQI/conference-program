#!/usr/bin/env python3
"""
Start a new conference year from the previous one.

    python3 new_year.py --year 2028 [--from-year 2027] [--site .] [--check]

Copies, from content/<from-year>/ to content/<year>/, the pages that every
year has: the home page, the top-level pages (call, registration, charter,
history, code of conduct, ...) and the _index.md of each section (schedule,
sessions, speakers, team, partners, ...). Individual talks, speakers, committee
members and partners are NOT copied, so nothing of the previous conference
shows up by accident. All copied pages get `year: <year>`, their menu entries
move to the new year, and they are set to `draft: true`: publish each one
once it has been updated.

Also:
  * hugo.toml: copies [params.<from-year>] (city, colours, logos) and the
    [[menu.<from-year>]] entries to the new year. It does not change
    currentYear or the "/" redirect; do that when the new site goes live.
  * assets/style/theme-<year>.scss: copy of the previous year's (colours!)
  * data/accepted-papers-<year>.json and posters-<year>.json: empty lists

It prints a checklist of what to adapt by hand. With --check nothing is written.
"""
import argparse
import re
import sys
from pathlib import Path


def latest_year(site):
    years = sorted(int(p.name) for p in (site / "content").iterdir() if p.is_dir() and p.name.isdigit())
    if not years:
        raise SystemExit("no content/<year>/ folders found")
    return str(years[-1])


def adapt_page(text, old, new):
    m = re.match(r"(---\s*\n)(.*?)(\n---\s*\n?)(.*)", text, re.S)
    if not m:
        return text
    front, body = m.group(2), m.group(4)
    front = re.sub(rf"^year:\s*{old}\s*$", f"year: {new}", front, flags=re.M)
    if not re.search(r"^year:", front, re.M):
        front += f"\nyear: {new}"
    front = re.sub(rf"^(\s+){old}:\s*$", rf"\g<1>{new}:", front, flags=re.M)   # menu: <year>:
    front = re.sub(r"^draft:.*$", "draft: true", front, flags=re.M)
    if not re.search(r"^draft:", front, re.M):
        front += "\ndraft: true"
    body = body.replace(f"/{old}/", f"/{new}/")
    return m.group(1) + front + m.group(3) + body


def copy_config_blocks(text, old, new):
    lines = text.split("\n")
    blocks, current = [], None
    for line in lines:
        s = line.strip()
        h = re.match(r"^\[\[?([^\]]+)\]\]?$", s)
        if h:
            name = h.group(1).split(".")
            current = [] if len(name) > 1 and name[0] in ("params", "menu", "menus") and name[1] == old else None
            if current is not None:
                blocks.append(current)
        if current is not None:
            current.append(line)
    if not blocks:
        return text, 0
    new_lines = []
    for block in blocks:
        for line in block:
            line = re.sub(rf"(\[\[?(?:params|menu|menus)\.){old}\b", rf"\g<1>{new}", line)
            line = line.replace(f"/{old}/", f"/{new}/").replace(f"'/{old}'", f"'/{new}'").replace(f'"/{old}"', f'"/{new}"')
            new_lines.append(line)
    # menus go after the last menu block of the old year, params after the last params block
    text += "\n\n# --- added by new_year.py for " + new + ": adapt city, logos, colours and menus ---\n" + "\n".join(new_lines) + "\n"
    return text, len(blocks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", required=True)
    parser.add_argument("--from-year")
    parser.add_argument("--site", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    site, new = Path(args.site), str(args.year)
    old = args.from_year or latest_year(site)
    src, dst = site / "content" / old, site / "content" / new
    if dst.exists():
        raise SystemExit(f"{dst} already exists")
    if not src.exists():
        raise SystemExit(f"{src} not found")

    writes = []
    for page in sorted(src.rglob("*.md")):
        rel = page.relative_to(src)
        top_level = len(rel.parts) == 1
        section_index = rel.name == "_index.md"
        if top_level or section_index:
            writes.append((dst / rel, adapt_page(page.read_text(encoding="utf-8"), old, new)))

    cfg = site / "hugo.toml"
    cfg_text, n_blocks = copy_config_blocks(cfg.read_text(encoding="utf-8"), old, new)
    writes.append((cfg, cfg_text))
    style_old = site / "assets" / "style" / f"theme-{old}.scss"
    if style_old.exists():
        writes.append((site / "assets" / "style" / f"theme-{new}.scss",
                       style_old.read_text(encoding="utf-8").replace(old, new)))
    for name in (f"accepted-papers-{new}.json", f"posters-{new}.json"):
        if not (site / "data" / name).exists():
            writes.append((site / "data" / name, "[]\n"))

    for path, text in writes:
        print(("would write " if args.check else "wrote ") + str(path.relative_to(site)))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    print(f"""
{len(writes) - 1} files from {old}; {n_blocks} hugo.toml blocks copied to {new}. Still to do by hand:
  - hugo.toml [params.{new}]: city, timeanddate_cityid, themeColor, logos
  - static/images/{new}/: logos and banner
  - assets/style/theme-{new}.scss: colours (--primary, --primary-txt, ...)
  - content/{new}/: update each page, then set draft: false
  - when the {new} site goes live: params.currentYear and the "/" redirect in netlify.toml
  - later: accepted papers, schedule, presenters and videos (README, steps 1-4)""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
