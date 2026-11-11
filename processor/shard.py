import faulthandler, hashlib, json, math, os, subprocess, sys, tempfile, time, traceback
from multiprocessing import Pool
from pathlib import Path
from common import *
from ocr import FIND, MODES, launch, ocr_task

SHARD, TOTAL = int(os.environ["SHARD"]), int(os.environ.get("TOTAL") or 16)
LINK, PASSED = os.environ["LINK"], int(os.environ.get("PASSED") or 0)
T0 = time.time()
BUDGET = 120  # seconds allowed for scrolling + screenshots; after that it stops and reads what it has
OCR_DEADLINE = int(os.environ.get("OCR_DEADLINE") or 50)  # extra OCR passes start only before this many seconds
HARD_LIMIT = int(os.environ.get("HARD_LIMIT") or 270)  # safety net: print where we are stuck, then stop
DPR = float(os.environ.get("DPR") or 2)  # screenshot sharpness
VW, VH = 1200, 1600
STEP = 0.5 if (not PASSED or PASSED / TOTAL <= 120) else 0.8  # screen step: 0.5 = 50% overlap, 0.8 = 20% overlap
faulthandler.dump_traceback_later(HARD_LIMIT, exit=True, file=sys.stderr)


def left():
    return BUDGET - (time.time() - T0)


def look(pg, tmp, tag):
    """Take one screenshot and read which sequence numbers are on screen."""
    f = str(tmp / f"look_{tag}.png")
    pg.screenshot(path=f)
    return f, sorted(parse_rows(ocr_task((f, "sharp")), PASSED))


def tidy(ks):
    if not ks:
        return ks
    med = ks[len(ks) // 2]
    return [k for k in ks if abs(k - med) <= 120]  # drop misread numbers far from the rest


def wheel(pg, dy):
    while abs(dy) > 1 and left() > 0:
        step = int(max(-2400, min(2400, dy)))
        pg.mouse.wheel(0, step)
        pg.wait_for_timeout(120)
        dy -= step


def seek(pg, tmp, target, files):
    """Scroll until the top of the screen shows a number just before `target`. Works by reading the numbers."""
    pg.mouse.move(VW // 2, VH // 2)
    ks, f = [], None
    for t in range(6):
        f, ks = look(pg, tmp, f"a{t}")
        ks = tidy(ks)
        if ks:
            break
        print(f"shard {SHARD}: page not readable yet, waiting ({t + 1}/6)")
        pg.wait_for_timeout(2000)
    if not ks:
        return None
    rpv = max(8, ks[-1] - ks[0] + 1)  # rows visible on one screen
    print(f"shard {SHARD}: first view shows {ks[0]}..{ks[-1]}")
    for it in range(8):
        if target <= 1 or left() <= 0:
            break
        diff = target - ks[0]
        if -2 <= diff <= rpv * 0.5:
            break
        wheel(pg, diff / rpv * VH * 0.95)
        pg.wait_for_timeout(1500)
        f, new = look(pg, tmp, f"b{it}")
        new = tidy(new)
        if new:
            ks = new
            rpv = max(8, ks[-1] - ks[0] + 1)
        print(f"shard {SHARD}: seek {it + 1}: now {ks[0]}..{ks[-1]} (want {target})")
    files.append(f)
    return rpv, ks[0]


def sweep(pg, tmp, files, n):
    last, same = None, 0
    for i in range(n):
        if left() <= 0:
            print(f"shard {SHARD}: time budget reached, using what we have")
            break
        pg.wait_for_timeout(1200)
        img = pg.screenshot()
        h = hashlib.md5(img).hexdigest()
        same = same + 1 if h == last else 0
        last = h
        if same >= 2:
            break  # nothing moves any more: bottom of the list
        f = str(tmp / f"w{i:03d}.png")
        Path(f).write_bytes(img)
        files.append(f)
        pg.mouse.wheel(0, int(VH * 0.6))


def main():
    from playwright.sync_api import sync_playwright
    tmp, files, ys = Path(tempfile.mkdtemp()), [], []
    first = max(1, SHARD * PASSED // TOTAL + 1 - 6) if PASSED else 1
    last = PASSED if (not PASSED or SHARD == TOTAL - 1) else (SHARD + 1) * PASSED // TOTAL + 6
    lo, hi = (max(1, first - 300), last + 300) if PASSED else (1, 10**6)  # numbers far outside this shard are misreads
    print(f"shard {SHARD}: needs numbers {first}..{last}")
    try:
        with sync_playwright() as p:
            br = launch(p)
            pg = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=DPR)
            pg.set_default_timeout(20000)
            try:
                pg.goto(f"https://drive.google.com/file/d/{drive_id(LINK)}/preview", wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print("page load problem (continuing):", str(e)[:200])
            frame, info = None, None
            for attempt in range(14):  # look for the scrolling list every 0.7s instead of one fixed 5s wait
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
                    pg.wait_for_timeout(1500)  # let the first pages paint
                    break
            print(f"shard {SHARD}: {len(pg.frames)} frames")
            if info:
                H, C = info["h"], info["c"]
                print(f"shard {SHARD}: scroll box found, height {H}, visible {C}")
                seg = H / TOTAL
                y, end, i = max(0, SHARD * seg - C * 0.5), min(H, (SHARD + 1) * seg + C * 0.5), 0
                while i < 80 and left() > 0:
                    frame.evaluate("y => window.__sc.scrollTop = y", y)
                    pg.wait_for_timeout(1100)
                    f = str(tmp / f"s{i:03d}.png")
                    pg.screenshot(path=f)
                    files.append(f)
                    ys.append(y)
                    print(f"shard {SHARD}: screenshot {i + 1} at {time.time() - T0:.0f}s")
                    i += 1
                    if y + C >= end or y + C >= H:
                        break
                    y += C * STEP
            elif PASSED == 0 and SHARD != 0:
                print(f"shard {SHARD}: nothing to do (list size unknown)")
            else:
                print(f"shard {SHARD}: no scroll box found, scrolling with the mouse and reading the numbers")
                got = seek(pg, tmp, first, files)
                if got:
                    rpv, top = got
                    n = min(25, math.ceil((last - top + 1) / max(6, rpv * 0.6)) + 1) if PASSED else 25
                    sweep(pg, tmp, files, n)
                else:
                    print(f"shard {SHARD}: could not read any numbers from the page")
            br.close()
    except Exception:
        traceback.print_exc()
    print(f"shard {SHARD}: {len(files)} screenshots, {time.time() - T0:.0f}s so far", flush=True)
    reads, loose, obs = [], [], []
    ymap = dict(zip(files, ys)) if len(files) == len(ys) else {}
    if files:
        with Pool(min(os.cpu_count() or 2, 4)) as pool:
            for n, mode in enumerate(MODES):
                if n and time.time() - T0 > OCR_DEADLINE:
                    print(f"shard {SHARD}: skipping OCR pass {n + 1}, time is short")
                    break
                texts = pool.map(ocr_task, [(f, mode) for f in files])
                for f, t in zip(files, texts):
                    strict = {k: v for k, v in parse_rows(t, PASSED).items() if lo <= k <= hi}
                    if strict:
                        reads.append(strict)
                    extra = {k: v for k, v in parse_loose(t, PASSED, strict).items() if lo <= k <= hi}
                    if extra:
                        loose.append(extra)
                    ks = tidy(sorted(strict))
                    if n == 0 and f in ymap and len(ks) >= 3:
                        obs.append([ymap[f], ks[0], ks[-1]])  # "at scroll position y the screen showed numbers a..b"
                print(f"shard {SHARD}: OCR pass {n + 1} ({mode}) done at {time.time() - T0:.0f}s", flush=True)
    dump = lambda rs: json.dumps([{str(k): v for k, v in r.items()} for r in rs])
    (WORK / f"loose_{SHARD}.json").write_text(dump(loose))
    (WORK / f"obs_{SHARD}.json").write_text(json.dumps(obs))
    (WORK / f"reads_{SHARD}.json").write_text(dump(reads))
    seen = set()
    for r in reads:
        seen.update(r)
    holes = [k for k in range(first, last + 1) if k not in seen]
    print(f"shard {SHARD}: {len(reads)} reads, {len(seen)} different rows, {len(holes)} numbers not read in {first}..{last}, done in {time.time() - T0:.0f}s")
    if holes:
        print(f"shard {SHARD}: not read: {holes[:20]}")
    if reads:
        k = sorted(reads[0])[:2]
        print("sample:", [(n, reads[0][n]) for n in k])


if __name__ == "__main__":
    main()
