#!/usr/bin/env python3
"""
Shift the paper ids of a HotCRP export, so that two exports can share one
data file without clashing ids.

    python3 adjust_pids.py posteronly.json posteronly-shifted.json --offset 1000

Typical use: talks and posters come from different HotCRP instances that both
number from 1. Shift the poster-only export by 1000 before sanitizing; talk and
poster ids then never overlap, which presenters-YEAR.yml and the #paper-<pid>
anchors rely on. "mergedwith" references are shifted as well.
"""
import argparse
import json
import sys
from pathlib import Path


def shift(entry, offset):
    if "pid" in entry:
        entry["pid"] += offset
    if "mergedwith" in entry:
        m = entry["mergedwith"]
        entry["mergedwith"] = [x + offset for x in m] if isinstance(m, list) else m + offset
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("legacy_offset", nargs="?", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--offset", type=int, default=None, help="default 1000")
    args = parser.parse_args(argv)
    offset = args.offset if args.offset is not None else (args.legacy_offset or 1000)

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    data = [shift(e, offset) for e in (data if isinstance(data, list) else [data])]
    Path(args.output).write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    print(f"shifted {len(data)} entries by {offset} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
