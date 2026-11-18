"""Second pipeline, stage 2: takes the screenshots complete_prepare.py's links point to.
No OCR and no text reading. Images go in scans/<slug>/ and their addresses go in the release data."""
import io, json, sys
from pathlib import Path
import requests
from PIL import Image
from common import drive_id
from ocr import FIND, launch

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCANS = ROOT / "scans"
WORK = Path(__file__).resolve().parent / "work"
VW, VH, DPR = 1200, 1600, 2
MAX_VIEWS = 150


def releases():
    out = []
    for p in DATA.glob("*.json"):
        if p.stem in ("state", "releases"):
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("meta"), dict):
            out.append((p, d))
    return out


def capture(did):
    """Scrolls the Drive viewer from the top to the bottom. One image per new view; repeats are dropped."""
    from playwright.sync_api import sync_playwright
    import hashlib
    views, last = [], None
    with sync_playwright() as p:
        br = launch(p)
        pg = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=DPR)
        pg.set_default_timeout(20000)
        pg.goto(f"https://drive.google.com/file/d/{did}/preview", wait_until="domcontentloaded", timeout=60000)
        info, frame = None, None
        for _ in range(30):
            pg.wait_for_timeout(700)
            for fr in pg.frames:
                try:
                    info = fr.evaluate(FIND)
                except Exception:
                    info = None
                if info:
                    frame = fr
                    break
            if info:
                break
        pg.wait_for_timeout(2000)
        if info:
            H, C = info["h"], info["c"]
            y = 0
            while len(views) < MAX_VIEWS:
                frame.evaluate("y => window.__sc.scrollTop = y", y)
                pg.wait_for_timeout(1100)
                img = pg.screenshot()
                digest = hashlib.md5(img).hexdigest()
                if digest != last:
                    views.append(img)
                    last = digest
                if y + C >= H:
                    break
                y += C * 0.9
        else:
            print("viewer not found; saving one screenshot only")
            views.append(pg.screenshot())
        br.close()
    return views


def save(views, folder, prefix):
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, png in enumerate(views, 1):
        name = f"{prefix}-{i:03d}.webp"
        Image.open(io.BytesIO(png)).convert("RGB").save(
            folder / name, "WEBP", lossless=True, quality=100, method=6)
        names.append(name)
    return names


def main():
    handed = json.loads((WORK / "links.json").read_text())
    article, links = handed["article"], handed["links"]
    rel = releases()
    targets = [(p, d) for p, d in rel if d["meta"].get("source") == article]
    print(f"article: {article} | releases on it: {len(targets)}")
    if not targets:
        print("no release matches this article yet")
        sys.exit(1)

    changed = []
    for kind, dids in links.items():
        if not dids:
            print(f"no {kind} link on the article")
            continue
        if kind == "names" and len(dids) > 1:
            print("several list links: names frames skipped (needs matching per list)")
            continue
        key = "scans" if kind == "names" else f"{kind}_scans"
        todo = [(p, d) for p, d in targets if not d["meta"].get(key)]
        if not todo:
            print(f"{kind}: already done")
            continue
        views = capture(dids[0])
        print(f"{kind}: {len(views)} page images captured")
        for p, d in todo:
            m = d["meta"]
            names = save(views, SCANS / m["slug"], kind)
            m[key] = [f"/scans/{m['slug']}/{n}" for n in names]
            changed.append((p, d))

    for p, d in changed:
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    print("releases updated:", len(changed))


if __name__ == "__main__":
    main()
