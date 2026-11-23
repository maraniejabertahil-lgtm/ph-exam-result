"""Puts the page images of LIVE releases into site/scans, and the "results expected" cards into site/expected,
right after build.py has built the site.

build.py wipes site/ on every build and does not copy scans/ or cards/, so every deploy has to add them back.
Only releases still inside the retention window (config.json "retention_days", default 14) are copied,
so expired scans never reach the site and the upload stays small.
The cards (made by expected_post.py, one small page + one picture each) are kept for config.json
"expected_card_days" (default 60) days, so the link in an old Facebook post keeps working for that long.
Standard library only."""
import json, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SCANS = ROOT / "scans"
CARDS = ROOT / "cards"
STAMP = "%Y-%m-%d %H:%M UTC"          # same format and same rule as live() in build.py
NOW = datetime.now(timezone.utc)


def copy_scans(cfg):
    if not SCANS.exists():
        print("no scans/ folder yet: nothing to copy")
        return
    keep_for = timedelta(days=int(cfg.get("retention_days", 14)))
    folders = images = expired = 0
    for p in sorted((ROOT / "data").glob("*.json")):
        if p.stem in ("state", "releases"):
            continue
        try:
            meta = json.loads(p.read_text())["meta"]
            slug = meta["slug"]
        except Exception:
            continue
        src = SCANS / slug
        if not src.is_dir():
            continue
        try:
            updated = datetime.strptime(meta.get("updated"), STAMP).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            updated = NOW
        if NOW - updated > keep_for:
            expired += 1
            continue
        shutil.copytree(src, SITE / "scans" / slug, dirs_exist_ok=True)
        folders += 1
        images += sum(1 for f in src.iterdir() if f.is_file())
    print(f"scans: {folders} live release folder(s), {images} image(s) copied; {expired} expired folder(s) left out")


def copy_cards(cfg):
    log_file = CARDS / "posts.json"
    if not log_file.exists():
        print("no cards/ log yet: no 'results expected' pages to copy")
        return
    keep_for = timedelta(days=int(cfg.get("expected_card_days", 60)))
    try:
        log = json.loads(log_file.read_text())
    except ValueError:
        print("cards/posts.json is unreadable: no 'results expected' pages copied")
        return
    copied = expired = 0
    for e in log if isinstance(log, list) else []:
        try:
            src = CARDS / e["slug"]
            made = datetime.strptime(e["created"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if not src.is_dir():
            continue
        if e.get("status") != "pending" and NOW - made > keep_for:
            expired += 1
            continue
        shutil.copytree(src, SITE / "expected" / e["slug"], dirs_exist_ok=True)
        copied += 1
    print(f"expected: {copied} 'results expected' page(s) copied; {expired} expired page(s) left out")


def main():
    if not SITE.exists():
        sys.exit("site/ not found: run processor/build.py first")
    cfg = json.loads((ROOT / "config.json").read_text())
    copy_scans(cfg)
    copy_cards(cfg)


if __name__ == "__main__":
    main()
