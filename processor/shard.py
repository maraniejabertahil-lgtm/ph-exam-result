import hashlib, json, os, subprocess, tempfile
from multiprocessing import Pool
from pathlib import Path
from common import *

SHARD, TOTAL = int(os.environ["SHARD"]), int(os.environ.get("TOTAL") or 16)
LINK, PASSED = os.environ["LINK"], int(os.environ.get("PASSED") or 0)
THR = (125, 150, 175)
FIND = """() => { let b=null,m=0; for (const e of document.querySelectorAll('*')) {
  if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
  if (e.scrollHeight > e.clientHeight+200 && e.scrollHeight > m) { m=e.scrollHeight; b=e; } }
  if (!b && document.scrollingElement && document.scrollingElement.scrollHeight > window.innerHeight+200) b=document.scrollingElement;
  if (!b) return null; window.__sc=b; return {h:b.scrollHeight, c:b.clientHeight}; }"""


def ocr_task(a):
    from PIL import Image
    f, thr = a
    im = Image.open(f).convert("L")
    box = im.point(lambda p: 255 if p > 235 else 0).getbbox()
    if not box:
        return ""
    o = f"{f}.{thr}.png"
    im.crop(box).point(lambda p: 255 if p > thr else 0).save(o)
    return subprocess.run(["tesseract", o, "-", "--psm", "6", "--dpi", "300", "-c", "preserve_interword_spaces=1"],
                          capture_output=True, text=True).stdout


def main():
    from playwright.sync_api import sync_playwright
    tmp, files = Path(tempfile.mkdtemp()), []
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1200, "height": 1600}, device_scale_factor=3)
        pg.goto(f"https://drive.google.com/file/d/{drive_id(LINK)}/preview", wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(2500)
        frame, info = None, None
        for fr in pg.frames:
            try:
                info = fr.evaluate(FIND)
            except Exception:
                info = None
            if info:
                frame = fr; break

        def shot(i):
            f = str(tmp / f"s{i:03d}.png"); pg.screenshot(path=f); files.append(f)

        if info:
            H, C = info["h"], info["c"]
            seg = H / TOTAL
            y, end, i = max(0, SHARD * seg - C * 0.5), min(H, (SHARD + 1) * seg + C * 0.5), 0
            while True:
                frame.evaluate("y => window.__sc.scrollTop = y", y)
                pg.wait_for_timeout(1300); shot(i); i += 1
                if y + C >= end or y + C >= H:
                    break
                y += C * 0.5
        elif SHARD == 0:
            last, same = None, 0
            pg.mouse.move(600, 800)
            for i in range(800):
                img = pg.screenshot(); h = hashlib.md5(img).hexdigest()
                same = same + 1 if h == last else 0; last = h
                if same >= 2:
                    break
                f = str(tmp / f"s{i:03d}.png"); Path(f).write_bytes(img); files.append(f)
                pg.mouse.wheel(0, 800); pg.wait_for_timeout(1300)
        br.close()
    print(f"shard {SHARD}: {len(files)} screenshots")
    with Pool(os.cpu_count() or 2) as pool:
        texts = pool.map(ocr_task, [(f, t) for f in files for t in THR])
    reads = [r for r in (parse_rows(t, PASSED) for t in texts) if r]
    (WORK / f"reads_{SHARD}.json").write_text(json.dumps([{str(k): v for k, v in r.items()} for r in reads]))
    print(f"shard {SHARD}: {len(reads)} reads, {sum(len(r) for r in reads)} rows")


if __name__ == "__main__":
    main()
