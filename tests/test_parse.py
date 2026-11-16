"""Offline checks against a synthetic snapshot (made-up class and teacher). No browser or sign-in needed:

    python -m unittest discover tests
"""
import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from classroom_parser import build_output, load_config, parse  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
REF = date(2026, 3, 10)          # a Tuesday


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class Dates(unittest.TestCase):
    def test_relative_and_absolute(self):
        cases = {
            "Due Tomorrow, 8:00 AM": "2026-03-11 08:00",
            "Due Today": "2026-03-10",
            "Due 11:59 PM": "2026-03-10 23:59",
            "Friday, 11:59 PM": "2026-03-13 23:59",
            "Tuesday": "2026-03-17",                      # same weekday means next week
            "Sep 29": "2026-09-29",
            "Due Sunday, Oct 18": "2026-10-18",            # explicit month/day wins over the weekday
            "Mar 3, 2025": "2025-03-03",
            "No due date": None,
            "": None,
        }
        for text, want in cases.items():
            self.assertEqual(parse.parse_due(text, REF), want, text)

    def test_year_rollover(self):
        self.assertEqual(parse.parse_due("Jan 5", date(2026, 12, 20)), "2027-01-05")

    def test_missing_dates_are_in_the_past(self):
        self.assertEqual(parse.as_past(parse.parse_due("Monday", REF), REF), "2026-03-09")
        self.assertEqual(parse.as_past("2026-11-02", REF), "2025-11-02")

    def test_post_date(self):
        self.assertEqual(parse.post_date(["Post by X", "X", "Created Mar 9"], REF), date(2026, 3, 9))
        self.assertEqual(parse.post_date(["Dec 20"], date(2026, 1, 5)), date(2025, 12, 20))
        self.assertEqual(parse.post_date(["8:56 AM"], REF), REF)


class Pages(unittest.TestCase):
    def test_class_names(self):
        self.assertEqual(parse.class_names(load("home.json")), {"NzAxMjM0NTY3ODkw": "Biology 101 - Period 2"})
        self.assertEqual(parse.match_class({"x": "Biology 101 - Period 2"}, "biology"), "x")
        self.assertIsNone(parse.match_class({"x": "Biology"}, "chem"))

    def test_classwork(self):
        e = load("snapshot.json")["classes"]["NzAxMjM0NTY3ODkw"]
        items = parse.classwork_items(e["classwork"]["text"], REF)
        self.assertEqual([(i["title"], i["type"], i["completed"]) for i in items], [
            ("Cell membrane lab report", "assignment", False),
            ("Mitosis worksheet", "assignment", True),
            ("Unit 3 slides", "material", None),
            ("Exit ticket: osmosis", "question", False),
        ])
        self.assertTrue(parse.status_loaded(e["classwork"]["text"]))
        self.assertFalse(parse.status_loaded("Assignment\nSomething\nDue Friday"))

    def test_items_skip_view_your_work(self):
        e = load("snapshot.json")["classes"]["NzAxMjM0NTY3ODkw"]
        kinds = sorted(i["kind"] for i in parse.items_in(e["classwork"]).values())
        self.assertEqual(kinds, ["assignment", "assignment", "material", "question"])

    def test_todo_page(self):
        snap = load("snapshot.json")
        todo = parse.todo_page_items(snap["todo"]["text"], REF)
        self.assertEqual(todo, [
            {"title": "Exit ticket: osmosis", "class_name": "Biology 101 - Period 2", "due": None},
            {"title": "Cell membrane lab report", "class_name": "Biology 101 - Period 2", "due": "2026-03-13 23:59"},
        ])

    def test_details(self):
        snap = load("snapshot.json")
        d = parse.parse_details(next(iter(snap["details"].values())), frozenset(snap["boilerplate"]))
        self.assertEqual(d["author"], "Ms. Rivera")
        self.assertEqual(d["points"], "100 points")
        self.assertEqual(d["instructions"], ["Write up the lab using the template. Include your data table."])
        self.assertEqual(d["attachments"], [{"name": "Lab report template", "kind": "doc",
                                             "url": "https://docs.google.com/document/d/TEMPLATE/edit"}])

    def test_posts_drop_auto_and_comments(self):
        e = load("snapshot.json")["classes"]["NzAxMjM0NTY3ODkw"]
        posts = parse.parse_posts(e["posts"], REF)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["text"], "Bring your lab notebook on Thursday.")
        self.assertEqual(posts[0]["links"][0]["name"], "Lab safety rules")
        self.assertEqual(len(parse.parse_posts(e["posts"], REF, include_auto=True)), 2)


class Output(unittest.TestCase):
    def setUp(self):
        self.out = build_output(load("snapshot.json"))
        self.cls = self.out["classes"][0]

    def test_statuses(self):
        status = {a["title"]: a["status"] for a in self.cls["assignments"]}
        self.assertEqual(status, {"Cell membrane lab report": "assigned", "Mitosis worksheet": "turned_in",
                                  "Exit ticket: osmosis": "assigned", "Punnett square practice": "missing"})

    def test_materials_and_attachments(self):
        m = self.cls["materials"][0]
        self.assertEqual(m["title"], "Unit 3 slides")
        self.assertEqual([a["kind"] for a in m["attachments"]], ["slides", "video"])

    def test_todo(self):
        self.assertTrue(self.out["todo_complete"])
        self.assertEqual(sum(t["missing"] for t in self.out["todo"]), 1)

    def test_cli_parse(self):
        r = subprocess.run([sys.executable, "-m", "classroom_parser", "--config", str(FIX / "nonexistent.json"),
                            "parse", str(FIX / "snapshot.json")], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 1)                 # an explicit config that doesn't exist is an error
        r = subprocess.run([sys.executable, "-m", "classroom_parser", "parse", str(FIX / "snapshot.json")],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), self.out)


class Config(unittest.TestCase):
    def test_unknown_key_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text('{"clases": []}')
            with self.assertRaises(ValueError):
                load_config(p)
            p.write_text('{"classes": ["Bio"], "account_index": 1, "_note": "ok"}')
            cfg = load_config(p)
            self.assertEqual(cfg.classes, ["Bio"])
            self.assertEqual(cfg.base_url, "https://classroom.google.com/u/1")


if __name__ == "__main__":
    unittest.main()
