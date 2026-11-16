"""Reading Google Classroom with Playwright, using the Chrome profile that `login` saved.

Read-only by design: it navigates to pages and reads their text. The only clicks are display toggles on the To-do
page (opening its sections and "View all"), which show more of a list. It never submits, turns in, comments,
types into a page, or downloads anything.
"""
import sys
import time
from datetime import datetime

from . import parse

GOOGLE_SIGNIN = ("accounts.google.com", "ServiceLogin")

# Playwright normally starts Chrome with a stand-in keychain and a plain-text password store. Chrome then can't
# decrypt the cookies the real sign-in saved (macOS encrypts them with the Keychain), treats the session as gone and
# deletes it. Dropping these two default flags launches Chrome with the real keychain.
KEEP_KEYCHAIN = ["--use-mock-keychain", "--password-store=basic"]

POSTS_JS = r"""() => [...document.querySelectorAll('[data-stream-item-id]')].map(el => ({
    id: el.getAttribute('data-stream-item-id'),
    lines: el.innerText.split('\n').map(s => s.trim()).filter(Boolean),
    links: [...el.querySelectorAll('a[href]')].map(a => ({url: a.href,
        name: (a.getAttribute('aria-label') || a.innerText || '').trim().split('\n')[0].replace(/^Attachment: /, '')}))
        .filter(l => /^https?:/.test(l.url) && !/classroom\.google\.com\/(u\/\d+\/)?(c|w|h|a)\//.test(l.url)
                     && !/accounts\.google|support\.google/.test(l.url))
}))"""


class NeedsLogin(Exception):
    """The saved session is gone: Classroom sent us to a sign-in page. Run `classroom-parser login`."""


def is_signin(url, cfg):
    text = (url or "")[:20000]
    return any(m in text for m in (*GOOGLE_SIGNIN, *cfg.signin_markers))


class profile_lock:
    """Only one process may drive the Chrome profile at a time (Chrome refuses a second instance)."""

    def __init__(self, profile, wait=600):
        self.path, self.wait = profile.parent / f"{profile.name}.lock", wait

    def _lock(self):
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "w")
        t0 = time.time()
        while True:
            try:
                self._lock()
                return self
            except OSError:
                if time.time() - t0 > self.wait:
                    self.f.close()
                    raise RuntimeError(f"the browser profile is busy (another run holds {self.path})")
                time.sleep(2)

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_UN)
        except OSError:
            pass
        self.f.close()


class Reader:
    """A signed-in Classroom browser session. Use as a context manager."""

    def __init__(self, cfg, headless=None, log=None):
        self.cfg = cfg
        self.headless = cfg.headless if headless is None else headless
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.boilerplate = frozenset()

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        if not self.cfg.profile.exists():
            raise NeedsLogin(f"no saved browser profile at {self.cfg.profile}")
        self._lock = profile_lock(self.cfg.profile).__enter__()
        try:
            self._pw = sync_playwright().start()
            self.ctx = self._pw.chromium.launch_persistent_context(
                str(self.cfg.profile), channel="chrome", headless=self.headless,
                ignore_default_args=KEEP_KEYCHAIN, viewport={"width": 1280, "height": 900})
        except Exception:
            self._cleanup()
            raise
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def _cleanup(self):
        for step in (lambda: self.ctx.close(), lambda: self._pw.stop(), lambda: self._lock.__exit__()):
            try:
                step()
            except Exception:
                pass

    def __exit__(self, *exc):
        self._cleanup()

    # ---------- pages ----------

    def read(self, url, scrolls=4):
        """Open a page and return {url, final_url, title, text, links}."""
        from playwright.sync_api import TimeoutError as PWTimeout
        page = self.page
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=4000)      # Classroom never goes fully idle
        except PWTimeout:
            pass
        if is_signin(page.url, self.cfg):
            raise NeedsLogin(url)
        for _ in range(scrolls):                                        # older posts load while scrolling
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(600)
        page.wait_for_timeout(int(self.cfg.page_delay_seconds * 1000))
        text = page.evaluate("() => (document.querySelector('main') || document.body).innerText")
        links = page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => ({
            href: a.href, text: (a.innerText || '').trim().slice(0, 200), label: a.getAttribute('aria-label') || ''}))""")
        return {"url": url, "final_url": page.url, "title": page.title(), "text": text, "links": links}

    def stream_posts(self):
        """Raw stream posts on the current page: [{id, lines, links}]."""
        try:
            return [p for p in self.page.evaluate(POSTS_JS) if p["id"] and p["lines"]]
        except Exception:
            return []

    def _section_open(self, name):
        lines = [l.strip() for l in self.page.inner_text("body").split("\n") if l.strip()]
        for i, l in enumerate(lines):
            if l == name:
                return "keyboard_arrow_up" in lines[i + 1:i + 4]
        return False

    def _press(self, locator):
        """Keyboard-activate a toggle: after "View all" tooltips and the footer can cover the buttons."""
        self.page.mouse.move(2, 2)
        locator.scroll_into_view_if_needed(timeout=3000)
        locator.focus(timeout=3000)
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(1200)

    def read_list(self, url):
        """The To-do and Missing pages are accordions: opening one section closes the others. Open each in turn
        (and "View all" inside a long one) and combine the text. Sets "expanded" if every section opened."""
        pg = self.read(url)
        page = self.page
        buttons = page.locator("button[aria-expanded][aria-label]")
        labels = [buttons.nth(i).get_attribute("aria-label") for i in range(buttons.count())]
        sections = [l for l in labels if l and parse.TODO_SECTION_RE.match(l)]
        chunks, complete = [pg["text"]], True
        for lab in sections:
            name = parse.TODO_SECTION_RE.match(lab).group(1)
            try:
                if not self._section_open(name):
                    self._press(page.locator(f'button[aria-label="{lab}"]'))
                if not self._section_open(name):
                    complete = False
                chunks.append(page.inner_text("body"))
            except Exception:
                complete = False
                continue
            more = page.get_by_text("View all", exact=True)
            for k in range(more.count()):
                try:
                    if more.nth(k).is_visible():
                        more.nth(k).click(timeout=3000)
                        page.wait_for_timeout(1500)
                        page.mouse.move(2, 2)
                        chunks.append(page.inner_text("body"))
                        break
                except Exception:
                    pass
        pg["text"] = "\n".join(chunks)
        pg["expanded"] = complete and bool(sections)
        return pg

    # ---------- whole runs ----------

    def home(self):
        home = self.read(self.cfg.base_url + "/h")
        # everything on the home page is sidebar / class-card text that repeats on every other page
        self.boilerplate = frozenset(parse.nonblank_lines(home["text"]))
        return home

    def list_classes(self):
        return parse.class_names(self.home())

    def collect_raw(self):
        """Read every page needed for one run and return the raw snapshot (page text + links), which
        `build_output` turns into structured JSON. Keeping the raw form lets you re-parse offline."""
        cfg, base = self.cfg, self.cfg.base_url
        snap = {"when": datetime.now().isoformat(timespec="seconds"), "base_url": base, "classes": {},
                "todo": None, "missing": None, "details": {}}
        home = self.home()
        snap["boilerplate"] = sorted(self.boilerplate)
        names = parse.class_names(home)
        if cfg.classes:
            chosen = {}
            for pat in cfg.classes:
                cid = parse.match_class(names, pat)
                if cid:
                    chosen[cid] = names[cid]
                else:
                    self.log(f"no class on the Classroom home page matches {pat!r}")
        else:
            chosen = names
        for cid, name in chosen.items():
            self.log(f"reading {name}")
            entry = {"name": name, "stream": self.read(f"{base}/c/{cid}")}
            entry["posts"] = self.stream_posts()
            entry["classwork"] = self.read(f"{base}/w/{cid}/t/all")
            if not parse.status_loaded(entry["classwork"]["text"]):
                self.page.wait_for_timeout(6000)              # turn-in statuses load after the list
                entry["classwork"] = self.read(f"{base}/w/{cid}/t/all")
            snap["classes"][cid] = entry
        if cfg.include_todo:
            snap["todo"] = self.read_list(base + "/a/not-turned-in/all")
            snap["missing"] = self.read_list(base + "/a/missing/all")
        if cfg.open_details:
            budget = cfg.max_details
            for cid, e in snap["classes"].items():
                items = {**parse.items_in(e["stream"]), **parse.items_in(e["classwork"])}
                for it in items.values():
                    if it["kind"] == "post" or it["url"] in snap["details"]:
                        continue
                    if budget <= 0:
                        self.log(f"stopped opening detail pages at max_details={cfg.max_details}")
                        return snap
                    budget -= 1
                    try:
                        snap["details"][it["url"]] = self.read(it["url"], scrolls=0)
                    except NeedsLogin:
                        raise
                    except Exception as ex:               # one bad page shouldn't stop the run
                        self.log(f"could not read {it['url']}: {str(ex).splitlines()[0][:120]}")
        return snap


def build_output(snap, include_auto_posts=False):
    """Raw snapshot -> the documented JSON output (see README). Pure: no browser needed."""
    ref = parse.ref_date(snap["when"])
    boiler = frozenset(snap.get("boilerplate", []))
    todo = parse.todo_page_items(snap["todo"]["text"], ref) if snap.get("todo") else []
    missing = parse.todo_page_items(snap["missing"]["text"], ref, missing=True) if snap.get("missing") else []
    details = {url: parse.parse_details(pg, boiler) for url, pg in snap.get("details", {}).items()}
    classes = [parse.build_class(cid, e["name"], e["stream"], e["classwork"], e.get("posts", []), ref,
                                 todo=todo, missing=missing, details=details, base_url=snap.get("base_url"),
                                 boilerplate=boiler, include_auto_posts=include_auto_posts)
               for cid, e in snap["classes"].items()]
    lists_complete = bool(snap.get("todo", {}) and snap["todo"].get("expanded")) and bool(
        snap.get("missing") and (snap["missing"].get("expanded") or "No work missing" in snap["missing"]["text"]))
    return {"fetched_at": snap["when"], "classes": classes,
            "todo": [{**t, "missing": False} for t in todo] + [{**t, "missing": True} for t in missing],
            "todo_complete": lists_complete}
