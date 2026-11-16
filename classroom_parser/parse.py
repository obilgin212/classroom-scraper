"""Pure parsing of Google Classroom page text and links. No browser, no network: everything here works on the
dicts that `scrape.read_page` returns ({"url", "final_url", "title", "text", "links"}), so it can be tested offline
against saved fixtures.

Classroom has no public HTML contract. These parsers read the *visible text* of each page, line by line, and look
for the labels Classroom shows ("Assignment", "Completed Assignment", "Due Tomorrow, 11:59 PM", ...). They expect the
Classroom interface in English.
"""
import re
from datetime import date, datetime, timedelta

CLASSROOM_HOST = "classroom.google.com"

# a Classroom item link: /c/<class id>/<kind>/<item id>   (kind: a = assignment, m = material, p = post, sa/mc = question)
ITEM_RE = re.compile(r"classroom\.google\.com/(?:u/\d+/)?c/([\w-]+)/([a-z]{1,3})/([\w-]+)")
CLASS_RE = re.compile(r"classroom\.google\.com/(?:u/\d+/)?c/([\w-]+)/?$")
ITEM_KIND = {"a": "assignment", "m": "material", "p": "post", "sa": "question", "mc": "question"}
SKIP_KINDS = {"sp"}                 # "View your work" pages: not readable by students
ATTACH_RE = re.compile(r"(drive|docs)\.google\.com|youtube\.com|youtu\.be|forms\.gle|forms\.google")

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                      "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Classwork page: the label line before each item, and whether it means "turned in"
WORK_KINDS = {"Assignment": False, "Completed Assignment": True, "Question": False, "Completed Question": True,
              "Quiz assignment": False, "Completed Quiz assignment": True}
MATERIAL_KINDS = {"Material"}
ICON_WORDS = {"assignment", "book", "quiz", "help", "live_help", "assignment_turned_in", "assignment_late"}

# To-do / Missing pages
TODO_SECTIONS = {"No due date", "This week", "Last week", "Next week", "Later", "Earlier", "Missing"}
TODO_SECTION_RE = re.compile(r"^(No due date|This week|Last week|Next week|Later|Earlier|Missing)\b")
TODO_MARKERS = {"assignment", "question", "quiz", "live_help", "assignment_late", "help"}

# details pages
DETAIL_STOP = {"Class comments", "Your work", "Private comments", "Your answer", "Add class comment"}
TYPE_WORDS = {"PDF", "Google Docs", "Google Slides", "Google Sheets", "Google Forms", "Google Drawings", "Link",
              "YouTube video", "Image", "Video", "Word", "Excel", "PowerPoint"}
SKIP_HOSTS = re.compile(r"(classroom|accounts|support|policies|myaccount|www)\.google\.com/?"
                        r"(?!.*(document|presentation|spreadsheets|forms|file|drive))|gstatic|googleusercontent")
TYPE_PREFIX = re.compile(r"^(PDF|Google \w+|Link|YouTube video|Image|Video|Word|Excel|PowerPoint):\s*")

# stream posts
AUTO_POST = re.compile(r'^(Assignment|Material|Question|Quiz assignment):\s*"|'
                       r"posted a new (assignment|material|question)", re.I)
SUBMISSION_RE = re.compile(r"\(\w{3} \d{1,2}, \d{4} at \d{1,2}:\d{2}")     # a student's own turned-in file

# interface chrome that shows up as text on every page
NOISE = re.compile(r"^(more_vert|add comment|class comments|add class comment|\d+ class comments?|"
                   r"announce something to your class|stream|classwork|people|grades|home|calendar|"
                   r"to-do|to review|enrolled|archived classes|settings|help|view all|see all|"
                   r"no class comments|view more|done|turned in|assigned|missing|edit|new announcement|"
                   r"skip to main content|main menu|classroom|resources|teaching|your work|add|add or create|"
                   r"mark as done|private comments|add comment to .*|more options|help and feedback|"
                   r"keyboard_arrow_\w+|expand|collapse|collapse all|collapse all sections|collapse topic|"
                   r"topic filter|all topics|assignment_ind|view your work|book|screen reader support enabled\.|"
                   r"all classes|no due date|this week|next week|later|earlier|pdf|google forms|image|link)$", re.I)


def clean(s):
    return (s or "").replace(" ", " ").replace("\xa0", " ").strip()


def nonblank_lines(text):
    return [clean(l) for l in (text or "").split("\n") if clean(l)]


def lines_of(text, boilerplate=frozenset()):
    """Meaningful lines of a page: no interface labels, no sidebar text that repeats on every page."""
    return [l for l in nonblank_lines(text) if len(l) > 2 and not NOISE.match(l) and l not in boilerplate]


# ---------- dates ----------

def _month_day(m, ref, year_group=3):
    y = int(m.group(year_group)) if m.group(year_group) else ref.year
    d = date(y, MONTHS[m.group(1)[:3]], int(m.group(2)))
    if not m.group(year_group) and (d - ref).days < -200:       # "Jan 5" seen in December means next year
        d = date(y + 1, d.month, d.day)
    return d


def parse_due(text, ref):
    """'Due Tomorrow, 8:00 AM' / 'Sep 29' / 'Friday, 11:59 PM' / 'Due 8:00 AM' -> 'YYYY-MM-DD[ HH:MM]' or None.

    `ref` is the date the page was read: Classroom shows relative dates ("Tomorrow", "Friday")."""
    t = re.sub(r"^Due\s+", "", clean(text), flags=re.I)
    if not t or re.match(r"no due date", t, re.I):
        return None
    tm = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", t, re.I)
    hhmm = None
    if tm:
        h = int(tm.group(1)) % 12 + (12 if tm.group(3).upper() == "PM" else 0)
        hhmm = f"{h:02d}:{tm.group(2)}"
    head = t.split(",")[0].strip().lower()
    d = None
    md = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?",
                   t.lower())
    if md:                                   # an explicit month/day wins ("Sunday, Oct 18")
        d = _month_day(md, ref)
    elif head == "today" or (tm and head == clean(tm.group(0)).lower()):
        d = ref
    elif head == "tomorrow":
        d = ref + timedelta(days=1)
    elif head == "yesterday":
        d = ref - timedelta(days=1)
    elif head in DAYS:
        d = ref + timedelta(days=(DAYS.index(head) - ref.weekday()) % 7 or 7)
    if not d:
        return None
    return d.isoformat() + (f" {hhmm}" if hhmm else "")


def as_past(due, ref):
    """Classroom's Missing list only holds past-due work: 'Monday' means last Monday, 'Mar 1' means this past March."""
    if not due:
        return due
    d = date.fromisoformat(due[:10])
    while d > ref:
        d = d - timedelta(days=7) if (d - ref).days <= 7 else date(d.year - 1, d.month, d.day)
    return d.isoformat() + due[10:]


def post_date(lines, ref):
    """Stream post header -> date: 'Created Sep 18' / 'Sep 18 (Edited Sep 20)' / '8:56 AM' / 'Yesterday'."""
    for l in lines[:6]:
        l = clean(l)
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:,\s*(\d{4}))?",
                      l.lower())
        if m:
            y = int(m.group(3)) if m.group(3) else ref.year
            d = date(y, MONTHS[m.group(1)], int(m.group(2)))
            if not m.group(3) and (d - ref).days > 200:       # "Dec 20" seen in January is last year
                d = date(y - 1, d.month, d.day)
            return d
        if re.search(r"\byesterday\b", l, re.I):
            return ref - timedelta(days=1)
        if re.search(r"\d{1,2}:\d{2}\s*[AP]M", l):
            return ref
    return None


# ---------- home page ----------

def class_names(home):
    """Classroom home page -> {class id: class name}. Each class card links to /c/<id> several times; the longest
    text on those links is the full name (the first is often just the avatar letter)."""
    texts = {}
    for a in home["links"]:
        m = CLASS_RE.search(a["href"].split("?")[0])
        if m:
            for t in (a.get("text", ""), a.get("label", "")):
                texts.setdefault(m.group(1), []).extend(x.strip() for x in (t or "").split("\n") if x.strip())
    return {cid: max(ts, key=len) if ts else cid for cid, ts in texts.items()}


def match_class(names, pattern):
    """First class id whose name contains `pattern` (case-insensitive), or None."""
    p = pattern.lower()
    return next((cid for cid, n in names.items() if p in n.lower()), None)


# ---------- links ----------

def items_in(pg):
    """Classroom items (assignments, materials, questions, posts) linked from a page: {key: {...}}."""
    found = {}
    for a in pg["links"]:
        m = ITEM_RE.search(a["href"])
        if not m:
            continue
        cid, kind, iid = m.groups()
        if kind in SKIP_KINDS:
            continue
        key = f"{cid}/{kind}/{iid}"
        name = clean((a.get("text") or a.get("label") or "").split("\n")[0])
        if key not in found or (name and not found[key]["title"]):
            base = a["href"].split("?")[0].rstrip("/")
            found[key] = {"id": iid, "class_id": cid, "kind": ITEM_KIND.get(kind, kind), "title": name,
                          "url": base if base.endswith("/details") else base + "/details"}
    return found


def attachment_kind(url):
    if "forms.gle" in url or "docs.google.com/forms" in url:
        return "form"
    if "docs.google.com/document" in url:
        return "doc"
    if "docs.google.com/spreadsheets" in url:
        return "sheet"
    if "docs.google.com/presentation" in url:
        return "slides"
    if re.search(r"(drive|docs)\.google\.com", url):
        return "drive"
    if re.search(r"youtube\.com|youtu\.be", url):
        return "video"
    return "link"


def attachments(pg):
    """Drive / Docs / Forms / YouTube links on a page."""
    seen, out = set(), []
    for a in pg["links"]:
        h = a["href"]
        if ATTACH_RE.search(h) and h not in seen:
            seen.add(h)
            name = (a.get("label") or a.get("text") or "").replace("Attachment: ", "").split("\n")[0][:150]
            out.append({"name": TYPE_PREFIX.sub("", clean(name)), "url": h, "kind": attachment_kind(h)})
    return out


# ---------- Classwork page ----------

def classwork_items(text, ref):
    """A class's Classwork page -> [{title, type, due, completed}] in page order.

    type is "assignment", "question", "quiz" or "material". `completed` is True/False for work and None for
    materials. Turn-in status loads after the list, so a page read too early shows everything as not completed;
    `status_loaded(text)` tells you whether it had arrived."""
    L = nonblank_lines(text)
    out = []
    for i, l in enumerate(L):
        if l not in WORK_KINDS and l not in MATERIAL_KINDS:
            continue
        j = i + 1
        while j < len(L) and L[j].lower() in ICON_WORDS:
            j += 1
        if j >= len(L):
            continue
        title, due = L[j], None
        for k in range(j + 1, min(j + 4, len(L))):
            if L[k].startswith("Due ") or L[k].lower() == "no due date":
                due = parse_due(L[k], ref)
                break
            if L[k] in WORK_KINDS or L[k] in MATERIAL_KINDS:
                break
        if l in MATERIAL_KINDS:
            out.append({"title": title, "type": "material", "due": None, "completed": None})
            continue
        base = l.replace("Completed ", "")
        typ = {"Assignment": "assignment", "Question": "question", "Quiz assignment": "quiz"}[base]
        out.append({"title": title, "type": typ, "due": due, "completed": WORK_KINDS[l]})
    return out


def status_loaded(text):
    """True if a Classwork page with assignments shows any turn-in status (or has no assignments to show)."""
    L = nonblank_lines(text)
    has_work = any(l in WORK_KINDS for l in L)
    return (not has_work) or any(l.startswith("Completed") for l in L)


# ---------- To-do / Missing pages ----------

def todo_page_items(text, ref, missing=False):
    """The To-do ("Assigned") or Missing page -> [{title, class_name, due}]. Sections must have been expanded."""
    L = nonblank_lines(text)
    out, section, seen = [], None, set()
    for i, l in enumerate(L):
        if l in TODO_SECTIONS:
            section = l
            continue
        if l.lower() in TODO_MARKERS and i + 2 < len(L):
            title, cls = L[i + 1], L[i + 2]
            nxt = L[i + 3] if i + 3 < len(L) else ""
            dated = section != "No due date" and nxt.lower() not in TODO_MARKERS \
                and not re.match(r"(posted|edited)\b", nxt, re.I)
            due = parse_due(nxt, ref) if dated else None
            if missing:
                due = as_past(due, ref)
            if (title, cls) not in seen:            # sections are read more than once
                seen.add((title, cls))
                out.append({"title": title, "class_name": cls, "due": due})
    return out


# ---------- item details page ----------

def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_details(pg, boilerplate=frozenset()):
    """An item's details page -> {title, author, points, due_text, instructions[], attachments[]}."""
    raw = nonblank_lines(pg["text"])
    title = re.sub(r"\s*-\s*Classroom\s*$", "", pg.get("title") or "").strip()
    t_i = next((i for i, l in enumerate(raw) if l == title), None)
    due_i = next((i for i, l in enumerate(raw)
                  if (t_i is None or i > t_i) and (l.startswith("Due ") or l == "No due date")), None)
    head = raw[t_i:due_i] if t_i is not None else []
    author = next((head[i + 1] for i, l in enumerate(head[:-1]) if l == "More options"), None)
    points = next((l for l in head if re.fullmatch(r"\d+ points?", l)), None)
    if due_i is not None:
        start = due_i + 1
    else:                       # questions / no-due items: body starts after the header block
        start = next((t_i + i + 1 for i, l in enumerate(head) if re.fullmatch(r"\d+ points?", l) or l == "|"),
                     (t_i or 0) + 5)
    body = []
    for l in raw[start:]:
        if l in DETAIL_STOP:
            break
        body.append(l)
    links, seen = [], set()
    for a in pg["links"]:
        h = a["href"]
        if not h.startswith("http") or h in seen or SKIP_HOSTS.search(h) or ITEM_RE.search(h):
            continue
        if "google.com" in h and not re.search(r"(drive|docs|forms)\.google\.com", h):
            continue
        seen.add(h)
        name = TYPE_PREFIX.sub("", clean((a.get("label") or a.get("text") or "")
                                         .replace("Attachment: ", "").split("\n")[0]))
        if name.lower().startswith("link to ") or not name:
            # link cards show the page title as a text line just before the URL
            i = next((k for k, l in enumerate(body) if l.rstrip("/") == h.rstrip("/")), None)
            name = body[i - 1] if i else h
        links.append({"name": name, "url": h, "kind": attachment_kind(h)})
    names = {_norm(x["name"]) for x in links}
    instructions = [l for l in body if l not in TYPE_WORDS and _norm(l) not in names and not l.startswith("http")
                    and not NOISE.match(l) and l not in ("•", "|") and l not in boilerplate]
    return {"title": title, "author": author, "points": points,
            "due_text": raw[due_i] if due_i is not None else "No due date",
            "instructions": instructions, "attachments": links}


# ---------- stream posts ----------

def post_body(lines):
    """Drop a stream post's header (author, 'Created …', date) and its comment controls."""
    body = []
    for i, l in enumerate(lines):
        if i < 6 and (l.startswith("Post by") or l.startswith("Created")
                      or re.fullmatch(r"\w{3} \d{1,2}( \(Edited .*\))?", l)
                      or re.fullmatch(r"\d{1,2}:\d{2}\s*[AP]M", clean(l)) or l in ("more_vert", "More options")):
            continue
        if l in ("Add comment", "Add class comment", "Class comments") or re.fullmatch(r"\d+ class comments?", l):
            break
        body.append(l)
    if lines and lines[0].startswith("Post by ") and body and body[0] == lines[0][8:]:
        body = body[1:]                     # the author's name repeats right after "Post by X"
    return body


def parse_posts(raw_posts, ref, include_auto=False):
    """Raw stream posts ({id, lines, links}) -> [{id, date, author, text, links, auto}].

    Classroom also puts an automatic post on the stream for each new assignment/material ("X posted a new
    assignment"); those are marked auto=True and dropped unless include_auto."""
    out = []
    for p in raw_posts:
        lines = [clean(l) for l in p.get("lines", []) if clean(l)]
        if not lines:
            continue
        auto = bool(AUTO_POST.search(" ".join(lines[:3])))
        if auto and not include_auto:
            continue
        d = post_date(lines, ref)
        body = post_body(lines)
        if not body or (not d and len(body) <= 2 and not auto):   # empty, or a link card inside another post
            continue
        author = lines[0][8:] if lines[0].startswith("Post by ") else None
        links = []
        for l in p.get("links", []):
            name = TYPE_PREFIX.sub("", clean(l.get("name", "")))
            if not SUBMISSION_RE.search(name) and l["url"] not in {x["url"] for x in links}:
                links.append({"name": name, "url": l["url"], "kind": attachment_kind(l["url"])})
        out.append({"id": p["id"], "date": d.isoformat() if d else None, "author": author,
                    "text": "\n".join(body), "links": links, "auto": auto})
    return out


# ---------- putting a class together ----------

def build_class(cid, name, stream, classwork, raw_posts, ref, todo=(), missing=(), details=None, base_url=None,
                boilerplate=frozenset(), include_auto_posts=False):
    """Combine one class's pages into the output record.

    Status of each assignment, strongest evidence first:
      * "missing"    Classroom's Missing list has it (past due, not turned in)
      * "turned_in"  the Classwork page marks it Completed
      * "assigned"   Classroom's To-do list has it, or the Classwork page shows it as not completed
      * "unknown"    turn-in status hadn't loaded on the Classwork page and no list mentions it
    """
    base_url = base_url or f"https://{CLASSROOM_HOST}"
    details = details or {}
    links = {**items_in(stream), **items_in(classwork)}
    by_title = {}
    for it in links.values():
        if it["title"] and it["kind"] != "post":
            by_title.setdefault(it["title"], it)
    loaded = status_loaded(classwork["text"])
    todo_t = {t["title"]: t for t in todo if t["class_name"] == name}
    miss_t = {t["title"]: t for t in missing if t["class_name"] == name}

    assignments, materials = [], []
    for w in classwork_items(classwork["text"], ref):
        link = by_title.get(w["title"])
        rec = {"title": w["title"], "id": link["id"] if link else None, "url": link["url"] if link else None}
        d = details.get(link["url"]) if link else None
        if w["type"] == "material":
            rec.update(type="material")
            if d:
                rec.update(description="\n".join(d["instructions"]), attachments=d["attachments"])
            materials.append(rec)
            continue
        if w["title"] in miss_t:
            status = "missing"
        elif w["completed"] and loaded:
            status = "turned_in"
        elif w["title"] in todo_t or loaded:
            status = "assigned"
        else:
            status = "unknown"
        due = w["due"] or (miss_t.get(w["title"]) or todo_t.get(w["title"]) or {}).get("due")
        rec.update(type=w["type"], due=due, status=status)
        if d:
            rec.update(points=d["points"], description="\n".join(d["instructions"]), attachments=d["attachments"])
        assignments.append(rec)

    # work on the To-do / Missing lists that the Classwork page didn't show (e.g. it hadn't scrolled that far)
    listed = {a["title"] for a in assignments}
    for src, status in ((miss_t, "missing"), (todo_t, "assigned")):
        for title, t in src.items():
            if title not in listed:
                link = by_title.get(title)
                assignments.append({"title": title, "id": link["id"] if link else None,
                                    "url": link["url"] if link else None, "type": "assignment",
                                    "due": t["due"], "status": status})
                listed.add(title)

    return {"id": cid, "name": name, "url": f"{base_url}/c/{cid}", "status_loaded": loaded,
            "assignments": assignments, "materials": materials,
            "posts": parse_posts(raw_posts, ref, include_auto=include_auto_posts)}


def ref_date(when):
    """ISO timestamp of the read -> date used to resolve 'Tomorrow', 'Friday', ..."""
    return datetime.fromisoformat(when).date()
