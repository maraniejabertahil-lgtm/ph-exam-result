"""Puts the page images of LIVE releases into site/scans, right after build.py has built the site.

build.py wipes site/ on every build and does not copy scans/, so every deploy has to add them back.
Only releases still inside the retention window (config.json "retention_days", default 30) are copied,
so expired scans never reach the site and the upload stays small. Standard library only."""
import json, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SCANS = ROOT / "scans"
STAMP = "%Y-%m-%d %H:%M UTC"          # same format and same rule as live() in build.py
NOW = datetime.now(timezone.utc)


def main():
    if not SITE.exists():
        sys.exit("site/ not found: run processor/build.py first")
    if not SCANS.exists():
        print("no scans/ folder yet: nothing to copy")
        return
    cfg = json.loads((ROOT / "config.json").read_text())
    keep_for = timedelta(days=int(cfg.get("retention_days", 30)))
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


if __name__ == "__main__":
    main()
