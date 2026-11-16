"""Settings: defaults, an optional JSON config file, and environment overrides. Nothing personal is built in."""
import json
import os
import shutil
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path

APP = "classroom-parser"


def default_profile_dir():
    """Where the dedicated Chrome profile (and so your saved sign-in cookies) lives."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP / "chrome-profile"


def default_config_file():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP / "config.json"


def find_chrome():
    """Path to an installed Google Chrome (the sign-in window runs real Chrome, not Playwright's Chromium)."""
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    elif sys.platform == "win32":
        cands = [str(Path(os.environ.get(v, d)) / "Google/Chrome/Application/chrome.exe")
                 for v, d in (("PROGRAMFILES", r"C:\Program Files"), ("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                              ("LOCALAPPDATA", str(Path.home() / "AppData/Local")))]
    else:
        cands = [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chrome")]
    return next((c for c in cands if c and Path(c).exists()), None)


@dataclass
class Config:
    profile_dir: str = ""
    chrome_path: str = ""
    # Google account slot in a profile that has several (the N in classroom.google.com/u/N/); 0 = first
    account_index: int = 0
    # Only read classes whose name contains one of these (case-insensitive). Empty = every class on the home page.
    classes: list = field(default_factory=list)
    # Extra text that marks a sign-in page (e.g. your school's single-sign-on host). Google's own is always detected.
    signin_markers: list = field(default_factory=list)
    headless: bool = True
    page_delay_seconds: float = 2.0
    include_todo: bool = True                # read the To-do and Missing lists (for turned-in/missing status)
    open_details: bool = True                # open each assignment/material page for its description and files
    max_details: int = 40                    # cap on detail pages per run (each one is a page load)
    include_auto_posts: bool = False         # keep the stream's automatic "posted a new assignment" items

    @property
    def base_url(self):
        return "https://classroom.google.com" + (f"/u/{self.account_index}" if self.account_index else "")

    @property
    def profile(self):
        return Path(self.profile_dir).expanduser() if self.profile_dir else default_profile_dir()

    @property
    def chrome(self):
        return self.chrome_path or find_chrome()


def load_config(path=None, **overrides):
    """Config from `path` (or $CLASSROOM_PARSER_CONFIG, or the default location if it exists), then env, then
    keyword overrides (None values are ignored)."""
    cfg = Config()
    p = Path(path or os.environ.get("CLASSROOM_PARSER_CONFIG") or default_config_file()).expanduser()
    known = {f.name for f in fields(Config)}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        unknown = [k for k in data if k not in known and not k.startswith("_")]
        if unknown:
            raise ValueError(f"{p}: unknown setting(s): {', '.join(unknown)}")
        for k, v in data.items():
            if k in known:
                setattr(cfg, k, v)
    elif path:
        raise FileNotFoundError(path)
    if os.environ.get("CLASSROOM_PARSER_PROFILE"):
        cfg.profile_dir = os.environ["CLASSROOM_PARSER_PROFILE"]
    if os.environ.get("CLASSROOM_PARSER_CHROME"):
        cfg.chrome_path = os.environ["CLASSROOM_PARSER_CHROME"]
    for k, v in overrides.items():
        if v is not None and k in known:
            setattr(cfg, k, v)
    return cfg
