"""Tests for the pipeline scripts. Run with:  python3 -m unittest discover tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_videos  # noqa: E402
import sanitize_hotcrp_json  # noqa: E402

PAPERS = [
    {"pid": 7, "title": "A rigorous and complete security proof of decoy-state BB84",
     "authors": [{"first": "Ada", "last": "Lovelace"}]},
    {"pid": 8, "title": "Uncloneable encryption from decoupling", "mergedwith": 100,
     "authors": [{"first": "Bob", "last": "Builder"}]},
    {"pid": 100, "title": "The uncloneable bit exists", "authors": []},
    {"pid": 63, "title": "Compressed Permutation Oracles",
     "authors": [{"first": "Joseph", "last": "Carolan"}]},
]

PROGRAM = """day,time,end,session,title,format,tags,location,chair,papers,speakers,note
2026-08-24,08:15,09:00,,Coffee Break,break,break,"Main Lobby",,,,
2026-08-24,9:00,9:20,,,contributed,,Room 140,Jane Chair,7,,
2026-08-24,09:20,09:40,contributed/8,Uncloneable encryption & the bit,contributed,,Room 140,,8,,
2026-08-24,09:40,10:00,invited/Goldin,,invited,,Room 140,,,Goldin,
2026-08-25,10:30,11:00,,Coffee Break,break,break,Main Lobby,,,,
"""


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


class Site:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "accepted-papers-2026.json").write_text(json.dumps(PAPERS))
        page = self.root / "content" / "2026" / "sessions" / "invited" / "Goldin.md"
        page.parent.mkdir(parents=True)
        page.write_text('---\ntitle: "Invited Talk: Less is More"\nchair: None\nvideoId: null\n---\n\nBio text.\n')
        (self.root / "program.csv").write_text(PROGRAM)


class GenerateScheduleTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.tmp.cleanup)
        self.root = self.site.root
        self.out = run("generate_schedule.py", "--year", "2026", "--program", "program.csv", cwd=self.root)

    def test_schedule_file(self):
        text = (self.root / "data" / "schedule-2026.yml").read_text()
        self.assertIn("time: '09:00'", text)  # times are always quoted
        schedule = yaml.safe_load(text)
        self.assertEqual([d["day"] for d in schedule], ["2026-08-24", "2026-08-25"])
        first = schedule[0]["sessions"]
        self.assertEqual([s["session"] for s in first],
                         ["stuff/coffee-break", "contributed/7", "contributed/8", "invited/Goldin"])
        self.assertEqual(first[1], {"session": "contributed/7", "time": "09:00", "end": "09:20",
                                    "location": "room-140"})

    def test_session_pages(self):
        page = (self.root / "content/2026/sessions/contributed/7.md").read_text()
        front = yaml.safe_load(page.split("---")[1])
        self.assertEqual(front["title"], PAPERS[0]["title"])  # taken from the paper
        self.assertEqual(front["papers"], [7])
        self.assertEqual(front["chair"], "Jane Chair")
        # existing page: body and unmanaged keys kept
        goldin = (self.root / "content/2026/sessions/invited/Goldin.md").read_text()
        self.assertIn("Bio text.", goldin)
        self.assertIn("videoId", goldin)
        self.assertIn("Goldin", yaml.safe_load(goldin.split("---")[1])["speakers"])

    def test_report_and_idempotent(self):
        self.assertIn("paper #63", self.out)        # accepted but not scheduled
        self.assertNotIn("paper #100", self.out)    # merged into #8, so it is fine
        again = run("generate_schedule.py", "--year", "2026", "--program", "program.csv", cwd=self.root)
        self.assertIn("everything up to date", again)

    def test_locations(self):
        locations = yaml.safe_load((self.root / "data/locations-2026.yml").read_text())
        self.assertEqual([l["key"] for l in locations], ["main-lobby", "room-140"])


class FetchVideosTest(unittest.TestCase):
    def test_matching(self):
        site = Site()
        self.addCleanup(site.tmp.cleanup)
        run("generate_schedule.py", "--year", "2026", "--program", "program.csv", cwd=site.root)
        playlist = {"entries": [
            {"id": "aaa", "title": "Compressed Permutation Oracles: Joseph Carolan"},
            {"id": "bbb", "title": "[QCrypt2026] Ada Lovelace: A rigorous and complete security proof of decoy state BB84"},
            {"id": "ccc", "title": "Invited Talk: Less is More"},
            {"id": "ddd", "title": "Uncloneable encryption & the bit"},
            {"id": "eee", "title": "Something else entirely"},
        ]}
        (site.root / "pl.json").write_text(json.dumps(playlist))
        (site.root / "data" / "videos-overrides-2026.yml").write_text('papers:\n  "100": {id: zzz}\n')
        out = run("fetch_videos.py", "--year", "2026", "--from-json", "pl.json", cwd=site.root)
        videos = yaml.safe_load((site.root / "data/videos-2026.yml").read_text())
        self.assertEqual(videos["papers"]["63"]["id"], "aaa")
        self.assertEqual(videos["papers"]["63"]["presenter"], "Joseph Carolan")
        self.assertEqual(videos["papers"]["7"]["presenter"], "Ada Lovelace")
        self.assertEqual(videos["sessions"]["invited/Goldin"]["id"], "ccc")
        self.assertEqual(videos["sessions"]["contributed/8"]["id"], "ddd")
        self.assertEqual(videos["papers"]["100"]["id"], "zzz")  # override
        self.assertIn("eee", out)  # reported, not linked

    def test_match_by_speaker(self):
        sessions = [("tutorial_aharonov", ["aharonov"]), ("tutorial_lami", ["Ludovico Lami"]),
                    ("panel", ["Ludovico Lami", "Someone Else"])]
        self.assertEqual(fetch_videos.match_by_speaker("QIP 2026 Tutorials: Dorit Aharonov", sessions),
                         "tutorial_aharonov")
        self.assertIsNone(fetch_videos.match_by_speaker("Tutorial: Ludovico Lami", sessions))  # ambiguous
        self.assertIsNone(fetch_videos.match_by_speaker("Tutorial: Nobody", sessions))

    def test_clean_title(self):
        self.assertEqual(fetch_videos.clean_title("Invited Talk: On obfuscation"), "On obfuscation")
        self.assertEqual(fetch_videos.clean_title("Contributed Talk: #8/#100 Uncloneable"), "Uncloneable")
        self.assertEqual(fetch_videos.clean_title("[QCrypt2025] Jian-Wei Pan: (Public Lecture) Dream"),
                         "Jian-Wei Pan: Dream")


class SanitizeTest(unittest.TestCase):
    def test_sanitize(self):
        with tempfile.TemporaryDirectory() as d:
            raw = [
                {"pid": 1, "title": "A", "decision": "Accept (talk)", "status": "accepted",
                 "some_new_hotcrp_field": "secret",
                 "authors": [{"first": "X", "last": "Y", "email": "x@y.org", "orcid": "0000"}],
                 "tags": [{"tag": "merge-1-2"}], "arxiv_number_url": "https://arxiv.org/abs/2503.19125v2"},
                {"pid": 2, "title": "B", "decision": "Accept (talk)", "authors": [], "tags": [{"tag": "merge-1-2"}]},
                {"pid": 3, "title": "C", "decision": "Reject", "authors": []},
            ]
            Path(d, "raw.json").write_text(json.dumps(raw))
            # an export with decisions needs --decision or --all
            self.assertEqual(sanitize_hotcrp_json.main([str(Path(d, "raw.json")), "-o", str(Path(d, "x.json"))]), 1)
            self.assertFalse(Path(d, "x.json").exists())
            sanitize_hotcrp_json.main([str(Path(d, "raw.json")), "-o", str(Path(d, "out.json")),
                                       "--decision", "accept", "--talk-type-from-decision"])
            out = json.loads(Path(d, "out.json").read_text())
        self.assertEqual([p["pid"] for p in out], [1, 2])          # rejected one dropped
        self.assertNotIn("email", json.dumps(out))
        self.assertNotIn("secret", json.dumps(out))   # unknown fields are dropped
        self.assertEqual(out[0]["authors"], [{"first": "X", "last": "Y"}])
        self.assertNotIn("decision", out[0])
        self.assertEqual(out[0]["mergedwith"], 2)
        self.assertEqual(out[1]["mergedwith"], 1)
        self.assertEqual(out[0]["options"]["arxiv-id"], "2503.19125")
        self.assertEqual(out[0]["options"]["talk-type"], "talk")


if __name__ == "__main__":
    unittest.main()
