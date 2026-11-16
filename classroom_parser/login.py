"""One-time sign-in (repeat whenever the session expires).

Opens a *normal* Google Chrome window, not an automated one, on a dedicated profile. You sign in by hand, through
Google's or your school's own sign-in page. This code never sees, types or stores a password: Chrome keeps the
cookies in the profile folder, and the reader reuses them.

You don't need to quit Chrome afterwards. The window is watched over Chrome's local debugging port; it finishes by
itself once Classroom (and Google Docs, so attachment links open too) load signed in, or as soon as you close it.
"""
import json
import socket
import subprocess
import time
import urllib.request

START_URLS = ["https://classroom.google.com/", "https://docs.google.com/document/u/0/"]
SIGNIN_HINTS = ("accounts.google.com", "ServiceLogin", "signin", "/login", "sso.", "idp.")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tabs(port):
    """The window's open tabs, or None while Chrome isn't answering."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return [t for t in json.load(r) if t.get("type") == "page"]
    except OSError:
        return None


def signed_in(url, host, markers=()):
    return host in url and not any(m in url for m in (*SIGNIN_HINTS, *markers))


def watch(port, proc, markers=(), auto_done=True, settle=4.0, poll=1.0, limit=1800):
    """Wait for the user. Returns 'signed-in', 'closed', 'exited' or 'timeout'."""
    t0, good_since, seen = time.time(), None, False
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            return "exited"
        tabs = _tabs(port)
        if tabs is None:
            time.sleep(poll)
            continue
        if tabs:
            seen = True
        elif seen:
            return "closed"                         # window closed; on macOS Chrome itself keeps running
        urls = [t.get("url", "") for t in tabs]
        both = any(signed_in(u, "classroom.google.com", markers) for u in urls) and \
            any(signed_in(u, "docs.google.com", markers) for u in urls)
        if auto_done and both:
            good_since = good_since or time.time()
            if time.time() - good_since >= settle:   # give Chrome a moment to write the cookies
                return "signed-in"
        else:
            good_since = None
        time.sleep(poll)
    return "timeout"


def _close(port, proc):
    """Close that Chrome cleanly so the cookies are flushed, without touching any other Chrome."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}").close()
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=10)


def login(cfg, extra_urls=(), echo=print):
    """Open the sign-in window and wait. Returns 0 on success, 1 on timeout."""
    chrome = cfg.chrome
    if not chrome:
        raise RuntimeError("Google Chrome wasn't found. Install it, or set chrome_path in the config "
                           "(or the CLASSROOM_PARSER_CHROME environment variable).")
    cfg.profile.mkdir(parents=True, exist_ok=True)
    urls = list(extra_urls) or START_URLS
    echo(f"A separate Chrome window opens, using its own profile ({cfg.profile}).")
    echo("1) Sign in with the Google account you use for Classroom.")
    if extra_urls:
        echo("2) Sign in on each tab, then close the window.\n")
    else:
        echo("2) Check that Classroom shows your classes and that Google Docs opens.")
        echo("   It finishes by itself once both are signed in, or when you close the window.\n")
    port = _free_port()
    proc = subprocess.Popen([chrome, f"--user-data-dir={cfg.profile}", f"--remote-debugging-port={port}",
                             "--no-first-run", "--no-default-browser-check", "--new-window", *urls],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    how = watch(port, proc, markers=tuple(cfg.signin_markers), auto_done=not extra_urls)
    if proc.poll() is None:
        _close(port, proc)
    echo({"signed-in": "Signed in. Session saved.", "closed": "Window closed. Session saved.",
          "exited": "Chrome closed.", "timeout": "Gave up after 30 minutes."}[how])
    return 1 if how == "timeout" else 0
