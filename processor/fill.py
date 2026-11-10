"""Gap filler. Runs between the shards and finish.
  python fill.py --check   -> prints how many numbers nobody read and sets the output need=yes/no
  python fill.py           -> scrolls the official preview to just the missing numbers, screenshots them,
                              reads them with OCR (sharper, all 3 thresholds) and saves reads_fill.json / loose_fill.json
Same method as the shards (screenshots + OCR), only aimed at the gaps."""
import bisect, faulthandler, json, os, re, subprocess, sys, tempfile, time, traceback
from multiprocessing import Pool
from pathlib import Path
from common import *

LINK, PASSED = os.environ.get("LINK", ""), int(os.environ.get("PASSED") or 0)
T0 = time.time()
BUDGET = int(os.environ.get("FILL_BUDGET") or 300)  # seconds for scrolling + screenshots
VW, VH = 1200, 1600
DPR = float(os.environ.get("DPR") or 2)
THR = (150, 125, 175)
TESS_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")
FIND = """() => { let b=null,m=0; for (const e of document.querySelectorAll('*')) {
  if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
  if (e.scrollHeight > e.clientHeight+200 && e.scrollHeight > m) { m=e.scrollHeight; b=e; } }
  if (!b && document.scrollingElement && document.scrollingElement.scrollHeight > window.innerHeight+200) b=document.scrollingElement;
  if (!b) return null; window.__sc=b; return {h:b.scrollHeight, c:b.clientHeight}; }"""


def left():
    return BUDGET - (time.time() - T0)


def known():
    strict, loose = set(), set()
    for f in WORK.glob("reads_*.json"):
        for r in json.loads(f.read_text()):
            strict.update(int(k) for k in r)
    for f in WORK.glob("loose_*.json"):
        if f.name == "loose_fill.json":
            continue
        for r in json.loads(f.read_text()):
            loose.update(int(k) for k in r)
    return strict, loose


def find_missing():
    job = json.loads((WORK / "job.json").read_text())
    passed = job.get("passed") or PASSED
    strict, loose = known()
    have = strict | loose
    return [n for n in range(1, passed + 1) if n not in have], passed


def clusters(nums, gap=12):
    out = []
    for n in nums:
        if out and n - out[-1][1] <= gap:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


# ---------- OCR (same recipe as shard.py) ----------
def parse_loose(text, announced, strict):
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    for line in text.splitlines():
        m = re.match(r"^\W*?(\d{1,6})\s+(.+)$", line.strip())
        if not m:
            continue
        n, name = int(m[1]), clean(m[2])
        if 1 <= n <= cap and n not in strict and n not in rows and len(name) >= 3:
            rows[n] = name
    return rows


def ocr_task(a):
    from PIL import Image
    f, thr = a
    im = Image.open(f).convert("L")
    box = im.point(lambda p: 255 if p > 235 else 0).getbbox()
    if not box:
        return ""
    o = f"{f}.{thr}.png"
    im.crop(box).point(lambda p: 255 if p > thr else 0).save(o)
    try:
        return subprocess.run(["tesseract", o, "-", "--psm", "6", "--dpi", "300", "-c", "preserve_interword_spaces=1"],
                              capture_output=True, text=True, env=TESS_ENV, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return ""


def tidy(ks):
    if not ks:
        return ks
    med = ks[len(ks) // 2]
    return [k for k in ks if abs(k - med) <= 120]


# ---------- number -> scroll position, from what the screenshots show ----------
class Map:
    def __init__(self, H, C, passed):
        self.H, self.C, self.passed = H, C, passed
        self.pts = {}  # number -> scrollTop where it was seen near the top / bottom edge

    def add(self, y, ks):
        ks = tidy(sorted(ks))
        if not ks:
            return
        self.pts[ks[0]] = y
        if len(ks) >= 3:
            self.pts[ks[-1]] = y + self.C * 0.95

    def est(self, n):
        """scrollTop at which number n sits near the top of the screen."""
        if len(self.pts) < 2:
            return (n - 1) / max(1, self.passed) * self.H
        ns = sorted(self.pts)
        ys = [self.pts[k] for k in ns]
        i = bisect.bisect_left(ns, n)
        if 0 < i < len(ns):                      # between two known points: straight line between them
            a, b = i - 1, i
        else:                                    # outside: use the slope of the whole list, not of one screen
            a, b = 0, len(ns) - 1
            if ns[b] == ns[a]:
                return ys[a]
            slope = (ys[b] - ys[a]) / (ns[b] - ns[a])
            edge = 0 if i == 0 else b
            return ys[edge] + (n - ns[edge]) * slope
        if ns[b] == ns[a]:
            return ys[a]
        return ys[a] + (n - ns[a]) * (ys[b] - ys[a]) / (ns[b] - ns[a])


def plan(m, cl, maxshots=12):
    """scrollTop positions that cover numbers lo..hi of one cluster."""
    lo, hi = cl
    C, H = m.C, m.H
    y = max(0, m.est(lo) - 0.3 * C)
    ys = []
    while len(ys) < maxshots:
        ys.append(min(max(0, y), max(0, H - C)))
        if y + C >= m.est(hi) + 0.2 * C:
            break
        y += 0.55 * C
    return ys


def main():
    missing, passed = find_missing()
    print(f"numbers nobody read: {len(missing)} of {passed}  first: {missing[:30]}")
    if "--check" in sys.argv:
        out(need="yes" if missing else "no")
        return
    if not missing:
        return
    faulthandler.dump_traceback_later(int(BUDGET) + 150, exit=True, file=sys.stderr)
    from playwright.sync_api import sync_playwright
    tmp = Path(tempfile.mkdtemp())
    reads, loose = [], []
    with Pool(min(os.cpu_count() or 2, 4)) as pool:   # fork the OCR workers before the browser starts

        def ocr_batch(files, thrs):
            jobs = [(f, t) for t in thrs for f in files]
            texts = pool.map(ocr_task, jobs)
            per150 = {}
            for (f, t), tx in zip(jobs, texts):
                strict = parse_rows(tx, passed)
                if strict:
                    reads.append(strict)
                extra = parse_loose(tx, passed, strict)
                if extra:
                    loose.append(extra)
                if t == 150:
                    per150[f] = sorted(strict)
            return per150

        try:
            with sync_playwright() as p:
                try:
                    br = p.chromium.launch(channel="chrome")
                except Exception:
                    br = p.chromium.launch()
                pg = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=DPR)
                pg.set_default_timeout(20000)
                try:
                    pg.goto(f"https://drive.google.com/file/d/{drive_id(LINK or json.loads((WORK / 'job.json').read_text())['link'])}/preview",
                            wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print("page load problem (continuing):", str(e)[:200])
                frame, info = None, None
                for _ in range(20):
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
                        pg.wait_for_timeout(1500)
                        break
                if not info:
                    print("could not find the scrolling list; nothing filled")
                    br.close()
                    return
                H, C = info["h"], info["c"]
                print(f"scroll box found, height {H}, visible {C}")
                m = Map(H, C, passed)

                def shoot(ys, tag):
                    files, yy = [], []
                    for i, y in enumerate(ys):
                        if left() <= 0:
                            print("time budget reached")
                            break
                        frame.evaluate("y => window.__sc.scrollTop = y", float(y))
                        pg.wait_for_timeout(900)
                        f = str(tmp / f"{tag}_{i:03d}.png")
                        pg.screenshot(path=f)
                        files.append(f); yy.append(y)
                    return files, yy

                # 1) calibrate: a few looks down the whole list
                cal_ys = [min(max(0, H * i / 12), max(0, H - C)) for i in range(13)]
                files, yy = shoot(cal_ys, "cal")
                for f, y in zip(files, yy):
                    pass
                obs = ocr_batch(files, (150,)) if files else {}
                for f, y in zip(files, yy):
                    m.add(y, obs.get(f, []))
                print(f"calibrated with {len(m.pts)} points at {time.time() - T0:.0f}s")

                # 2) aim at the gaps, check, and if still missing aim again with the better map
                for rnd in (1, 2):
                    strict_now = set()
                    for r in reads:
                        strict_now.update(r)
                    loose_now = set()
                    for r in loose:
                        loose_now.update(r)
                    still = [n for n in missing if n not in strict_now and n not in loose_now]
                    if rnd == 2 and still:
                        print(f"round 2: {len(still)} still missing: {still[:30]}")
                    if not still or left() <= 0:
                        break
                    ys = []
                    for cl in clusters(still):
                        ys += plan(m, cl)
                    ys = sorted(set(round(y) for y in ys))
                    print(f"round {rnd}: {len(still)} numbers, {len(ys)} screenshots")
                    files, yy = shoot(ys, f"r{rnd}")
                    if not files:
                        break
                    obs = ocr_batch(files, THR)
                    for f, y in zip(files, yy):
                        m.add(y, obs.get(f, []))
                    print(f"round {rnd} done at {time.time() - T0:.0f}s")
                br.close()
        except Exception:
            traceback.print_exc()
    (WORK / "reads_fill.json").write_text(json.dumps([{str(k): v for k, v in r.items()} for r in reads]))
    (WORK / "loose_fill.json").write_text(json.dumps([{str(k): v for k, v in r.items()} for r in loose]))
    got = set()
    for r in reads + loose:
        got.update(r)
    left_over = [n for n in missing if n not in got]
    print(f"filled {len(missing) - len(left_over)} of {len(missing)}; still missing {len(left_over)} {left_over[:30]}  ({time.time() - T0:.0f}s)")


if __name__ == "__main__":
    main()
