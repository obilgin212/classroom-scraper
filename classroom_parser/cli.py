"""Command line: `classroom-parser login | classes | fetch | parse`.

Exit codes: 0 ok, 1 error, 3 not signed in (run `login`).
"""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import default_config_file, load_config


def _write(data, out):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out and out != "-":
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="classroom-parser",
                                 description="Read your Google Classroom (read-only) and print it as JSON.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--config", help=f"JSON config file (default: {default_config_file()} if it exists)")
    ap.add_argument("--profile", help="Chrome profile folder holding the saved sign-in")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("login", help="open Chrome so you can sign in (first time, and when the session expires)")
    s.add_argument("urls", nargs="*", help="open these pages instead of Classroom + Docs (closes when you close it)")

    s = sub.add_parser("classes", help="list the classes on your Classroom home page")
    s.add_argument("--json", action="store_true")
    s.add_argument("--headed", action="store_true", help="show the browser window")

    s = sub.add_parser("fetch", help="read Classroom and output JSON")
    s.add_argument("-o", "--output", help="write JSON here instead of stdout")
    s.add_argument("--raw", help="also save the raw page snapshot here (re-parse later with `parse`)")
    s.add_argument("-c", "--class", dest="classes", action="append",
                   help="only classes whose name contains this (repeatable; overrides the config)")
    s.add_argument("--no-details", action="store_true", help="don't open each item's page")
    s.add_argument("--no-todo", action="store_true", help="skip the To-do and Missing lists")
    s.add_argument("--max-details", type=int)
    s.add_argument("--headed", action="store_true", help="show the browser window")

    s = sub.add_parser("parse", help="turn a raw snapshot (from fetch --raw) into JSON, offline")
    s.add_argument("snapshot")
    s.add_argument("-o", "--output")

    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config, profile_dir=a.profile)
    except (OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 1

    if a.cmd == "parse":
        from .scrape import build_output
        snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
        _write(build_output(snap, cfg.include_auto_posts), a.output)
        return 0

    if a.cmd == "login":
        from .login import login
        return login(cfg, a.urls)

    from .scrape import NeedsLogin, Reader, build_output
    if a.cmd == "fetch":
        if a.classes:
            cfg.classes = a.classes
        if a.no_details:
            cfg.open_details = False
        if a.no_todo:
            cfg.include_todo = False
        if a.max_details is not None:
            cfg.max_details = a.max_details
    try:
        with Reader(cfg, headless=False if a.headed else None) as r:
            if a.cmd == "classes":
                names = r.list_classes()
                if a.json:
                    _write([{"id": k, "name": v} for k, v in names.items()], None)
                else:
                    for v in names.values():
                        print(v)
                return 0
            snap = r.collect_raw()
    except NeedsLogin as e:
        print(f"Not signed in ({e}). Run: classroom-parser login", file=sys.stderr)
        return 3
    except Exception as e:
        msg = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        if "ProcessSingleton" in msg or ("profile" in msg.lower() and "in use" in msg.lower()):
            msg = "the Chrome profile is open in another window; close that window and retry"
        print(f"error: {msg}", file=sys.stderr)
        return 1
    if a.raw:
        _write(snap, a.raw)
    _write(build_output(snap, cfg.include_auto_posts), a.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
