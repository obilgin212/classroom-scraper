"""Pre-publish check: fail if anything personal, school-specific or secret-looking is in the repo files.

    python scrub_check.py

Add your own words to FORBIDDEN in a local, uncommitted file `scrub_words.txt` (one regex per line).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECRETS = [r"ghp_[A-Za-z0-9]{20,}", r"github_pat_", r"AIza[0-9A-Za-z_-]{30,}", r"ya29\.", r"sk-[A-Za-z0-9]{20,}",
           r"-----BEGIN [A-Z ]*PRIVATE KEY", r"SAPISID|__Secure-|SSID=|HSID=", r"[\w.+-]+@(?!example\.)[\w-]+\.[\w.]+",
           r"/Users/\w+", r"C:\\Users\\\w+", r"/home/\w+"]
SKIP = {".git", "__pycache__", "scrub_words.txt"}


def main():
    words = SECRETS[:]
    extra = ROOT / "scrub_words.txt"
    if extra.exists():
        words += [w.strip() for w in extra.read_text().splitlines() if w.strip() and not w.startswith("#")]
    bad = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or SKIP & set(rel.parts) or p.name == "scrub_check.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            bad.append(f"{rel}: binary file")
            continue
        for i, line in enumerate(text.split("\n"), 1):
            for pat in words:
                if re.search(pat, line, re.I):
                    bad.append(f"{rel}:{i}: [{pat}] {line.strip()[:120]}")
    if bad:
        print("\n".join(bad))
        sys.exit(f"\n✗ {len(bad)} hit(s)")
    print("✓ scrub clean")


if __name__ == "__main__":
    main()
