# classroom-scraper

Read **your own** Google Classroom as JSON (installs the `classroom-parser` command): your classes, assignments with due dates and turned-in / missing
status, materials and their attachments, and stream posts.

It works the way you do: through the Classroom website, in a Chrome window you signed in to yourself. You don't
need an API key, a Google Cloud project or admin approval, which school accounts often can't get.

* **Read-only.** It opens pages and reads their text. It never turns anything in, comments, edits, submits a form
  or downloads files. The only clicks are the To-do page's section toggles and "View all", which just show more of
  the list.
* **Your sign-in stays yours.** You sign in by hand in a normal Chrome window. This tool never sees, types or stores
  a password. The session lives in a dedicated Chrome profile on your computer, apart from your everyday one.

## Requirements

* Python 3.9+
* Google Chrome (the real browser: Playwright drives your installed Chrome, not its own Chromium)
* macOS, Windows or Linux
* Classroom set to **English** (the parser reads the interface's labels, like "Due Tomorrow" and "Completed")

## Install

```bash
git clone https://github.com/obilgin212/classroom-scraper.git
cd classroom-scraper
pip install .
```

Or without installing: `pip install -r requirements.txt`, then run `python -m classroom_parser` wherever this README
says `classroom-parser`.

## Use

**1. Sign in (once, and again whenever the session expires, often every week or two):**

```bash
classroom-parser login
```

A separate Chrome window opens on Classroom and Google Docs. Sign in with the account you use for Classroom. The
window closes by itself once both load signed in, or you can just close it.

**2. See which classes it finds:**

```bash
classroom-parser classes
```

**3. Fetch everything as JSON:**

```bash
classroom-parser fetch -o classroom.json
classroom-parser fetch -c "Biology" -c "Algebra" -o some.json     # only classes whose name contains these
classroom-parser fetch --no-details                               # faster: skip opening each item's page
```

`fetch` opens several pages per class plus one page for each assignment and material (capped by `max_details`), so a
full run takes a few minutes. Add `--headed` to watch it.

If the session has expired, `classes` and `fetch` exit with code **3** and tell you to run `login` again.

### Re-parse offline

`fetch --raw raw.json` also saves the raw page text it read. `classroom-parser parse raw.json` rebuilds the JSON from
it without opening a browser. That is handy when you change the parser, or when Classroom changes its pages.

### From Python

```python
from classroom_parser import load_config, Reader, NeedsLogin, build_output

cfg = load_config(classes=["Biology"])
try:
    with Reader(cfg) as r:
        data = build_output(r.collect_raw())
except NeedsLogin:
    print("run: classroom-parser login")
```

## Output

```jsonc
{
  "fetched_at": "2026-03-10T16:00:00",
  "classes": [
    {
      "id": "NzAxMjM0NTY3ODkw",
      "name": "Biology 101 - Period 2",
      "url": "https://classroom.google.com/c/NzAxMjM0NTY3ODkw",
      "status_loaded": true,             // false: turn-in status hadn't loaded, so "unknown" may appear
      "assignments": [
        {
          "title": "Cell membrane lab report",
          "id": "LAB1",
          "url": "https://classroom.google.com/c/.../a/LAB1/details",
          "type": "assignment",          // assignment | question | quiz
          "due": "2026-03-13 23:59",     // "YYYY-MM-DD", "YYYY-MM-DD HH:MM" or null
          "status": "assigned",          // assigned | turned_in | missing | unknown
          "points": "100 points",        // with details on
          "description": "Write up the lab using the template.",
          "attachments": [{"name": "Lab report template", "url": "https://docs.google.com/...", "kind": "doc"}]
        }
      ],
      "materials": [
        {"title": "Unit 3 slides", "id": "SLD1", "url": "...", "type": "material",
         "description": "Slides from class.", "attachments": [...]}
      ],
      "posts": [
        {"id": "P1", "date": "2026-03-09", "author": "Ms. Rivera",
         "text": "Bring your lab notebook on Thursday.", "links": [...], "auto": false}
      ]
    }
  ],
  "todo": [                              // Classroom's own To-do and Missing lists, across all classes
    {"title": "Cell membrane lab report", "class_name": "Biology 101 - Period 2",
     "due": "2026-03-13 23:59", "missing": false}
  ],
  "todo_complete": true                  // every section of both lists was opened and read
}
```

How `status` is decided, strongest evidence first: on Classroom's **Missing** list → `missing`; marked
**Completed** on the Classwork page → `turned_in`; on the **To-do** list or shown as not completed → `assigned`;
otherwise `unknown`. Attachment `kind` is one of `doc`, `sheet`, `slides`, `form`, `drive`, `video`, `link`.

Relative dates ("Tomorrow", "Friday") are resolved against the time of the fetch.

## Configuration

Everything is optional. Put a JSON file at the default location (shown in `classroom-parser --help`; on macOS
`~/Library/Application Support/classroom-parser/config.json`), or pass `--config path.json`. See
[`examples/config.example.json`](examples/config.example.json).

| key | default | what it does |
|---|---|---|
| `classes` | `[]` (all) | Only read classes whose name contains one of these (case-insensitive) |
| `signin_markers` | `[]` | Text in the URL of your school's single-sign-on page, so an expired session is noticed there too. Google's own sign-in is always detected |
| `account_index` | `0` | Which Google account in the profile (the `N` in `classroom.google.com/u/N/`) |
| `profile_dir` | per-OS app-data folder | Where the dedicated Chrome profile lives |
| `chrome_path` | auto-detected | Path to Google Chrome |
| `headless` | `true` | Read without showing a window |
| `page_delay_seconds` | `2` | Extra wait after each page loads |
| `include_todo` | `true` | Read the To-do and Missing lists (needed for `missing` status) |
| `open_details` | `true` | Open each assignment/material for its description and attachments |
| `max_details` | `40` | Cap on detail pages per run |
| `include_auto_posts` | `false` | Keep the stream's automatic "posted a new assignment" items |

Environment overrides: `CLASSROOM_PARSER_CONFIG`, `CLASSROOM_PARSER_PROFILE`, `CLASSROOM_PARSER_CHROME`.

## Tests

The tests run offline against a made-up snapshot in `tests/fixtures/`. They need no sign-in and no browser:

```bash
python -m unittest discover tests
```

## Good to know

* **Keep the profile folder private.** It holds your signed-in Google session. Don't commit it, sync it to a shared
  drive or send it to anyone. `.gitignore` already excludes the usual output and profile names.
* **It reads the page text, not an API.** When Google redesigns Classroom, parsing may break. Save a `--raw`
  snapshot, adjust `classroom_parser/parse.py`, and check with `classroom-parser parse`.
* **macOS keychain:** the reader launches Chrome with the real Keychain (not Playwright's stand-in). Otherwise
  Chrome can't decrypt the saved cookies and throws the session away. macOS may ask once to allow access.
* Only one run can use the profile at a time; a second one waits for the first.
* Use it for your own account, and follow your school's rules about automated access.

## License

See [LICENSE](LICENSE).
