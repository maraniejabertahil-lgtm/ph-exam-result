"""Gap filler: screenshots + OCR again, aimed only at numbers nobody read. Runs between the shards and finish.
  python fill.py --check   decides how many fill jobs are needed (sets outputs need / k / matrix)
  python fill.py           one fill job (FILL_SHARD of FILL_TOTAL): scrolls to its share of the gaps and reads them
The scroll positions come from obs_*.json that the shards saved ("at scroll y the screen showed numbers a..b"),
so no search is needed. Still-missing numbers get a last, sharper look (browser scale 3)."""
import bisect, faulthandler, json, math, os, sys, tempfile, time, traceback
from multiprocessing import Pool
from pathlib import Path
from common import *
from ocr import FIND, launch, ocr_task

LINK, PASSED = os.environ.get("LINK", ""), int(os.environ.get("PASSED") or 0)
T0 = time.time()
BUDGET = int(os.environ.get("FILL_BUDGET") or 200)   # seconds for scrolling + screenshots
PER_JOB = 5                                          # about this many gap-clusters per fill job
MAX_JOBS = 20
VW, VH = 1200, 1600


def left():
    return BUDGET - (time.time() - T0)


def known():
    strict, loose = set(), set()
    for f in WORK.glob("reads_*.json"):
        for r in json.loads(f.read_text()):
            strict.update(int(k) for k in r)
    for f in WORK.glob("loose_*.json"):
        for r in json.loads(f.read_text()):
            loose.update(int(k) for k in r)
    return strict, loose


def find_missing():
    job = json.loads((WORK / "job.json").read_text())
    passed = job.get("passed") or PASSED
    strict, loose = known()
    have = strict | loose
    return [n for n in range(1, passed + 1) if n not in have], passed, job


def clusters(nums, gap=12):
    out = []
    for n in nums:
        if out and n - out[-1][1] <= gap:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def tidy(ks):
    if not ks:
        return ks
    med = ks[len(ks) // 2]
    return [k for k in ks if abs(k - med) <= 120]


class Map:
    """number -> scroll position, learned from what screenshots showed."""

    def __init__(self, H, C, passed):
        self.H, self.C, self.passed = H, C, passed
        self.pts = {}
        self._ns = self._ys = None

    def add(self, y, ks):
        ks = tidy(sorted(ks))
        if ks:
            self.pts[ks[0]] = y
            if len(ks) >= 3:
                self.pts[ks[-1]] = y + self.C * 0.95
            self._ns = None

    def est(self, n):
        """scrollTop at which number n sits near the top of the screen."""
        if len(self.pts) < 2:
            return (n - 1) / max(1, self.passed) * self.H
        if self._ns is None:
            self._ns = sorted(self.pts)
            self._ys = [self.pts[k] for k in self._ns]
        ns, ys = self._ns, self._ys
        i = bisect.bisect_left(ns, n)
        if 0 < i < len(ns):
            a, b = i - 1, i
        else:                                    # outside the known range: slope of the whole list
            a, b = 0, len(ns) - 1
            if ns[b] == ns[a]:
                return ys[a]
            edge = 0 if i == 0 else b
            return ys[edge] + (n - ns[edge]) * (ys[b] - ys[a]) / (ns[b] - ns[a])
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


def open_page(br, dpr, link):
    pg = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=dpr)
    pg.set_default_timeout(20000)
    try:
        pg.goto(f"https://drive.google.com/file/d/{drive_id(link)}/preview", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print("page load problem (continuing):", str(e)[:200])
    for _ in range(20):
        pg.wait_for_timeout(700)
        for fr in pg.frames:
            try:
                info = fr.evaluate(FIND)
            except Exception:
                info = None
            if info:
                pg.wait_for_timeout(1500)
                return pg, fr, info
    return pg, None, None


def main():
    missing, passed, job = find_missing()
    cl_all = clusters(missing)
    k = max(1, min(MAX_JOBS, math.ceil(len(cl_all) / PER_JOB)))
    print(f"numbers nobody read: {len(missing)} of {passed} in {len(cl_all)} places; first: {missing[:30]}")
    if "--check" in sys.argv:
        out(need="yes" if missing else "no", k=k, matrix=json.dumps(list(range(k))))
        return
    me, total = int(os.environ.get("FILL_SHARD") or 0), int(os.environ.get("FILL_TOTAL") or 1)
    mine = cl_all[me::total]
    ms = set(missing)
    mine_nums = [n for c in mine for n in range(c[0], c[1] + 1) if n in ms]
    print(f"fill job {me + 1}/{total}: {len(mine)} places, {len(mine_nums)} numbers")
    if not mine:
        return
    link = LINK or job["link"]
    faulthandler.dump_traceback_later(int(BUDGET) + 150, exit=True, file=sys.stderr)
    from playwright.sync_api import sync_playwright
    tmp = Path(tempfile.mkdtemp())
    reads, loose = [], []
    got = lambda: set().union(*[set(r) for r in reads + loose]) if (reads or loose) else set()
    with Pool(min(os.cpu_count() or 2, 4)) as pool:   # OCR workers are forked before the browser starts

        def read(files, modes):
            jobs = [(f, m) for m in modes for f in files]
            per = {}
            for (f, mode), tx in zip(jobs, pool.map(ocr_task, jobs)):
                strict = parse_rows(tx, passed)
                if strict:
                    reads.append(strict)
                extra = parse_loose(tx, passed, strict)
                if extra:
                    loose.append(extra)
                if mode == modes[0]:
                    per[f] = sorted(strict)
            return per

        try:
            with sync_playwright() as p:
                br = launch(p)
                pg, frame, info = open_page(br, 2, link)
                if not info:
                    print("could not find the scrolling list; nothing filled")
                    br.close()
                    return
                H, C = info["h"], info["c"]
                m = Map(H, C, passed)
                for f in WORK.glob("obs_*.json"):
                    for y, lo, hi in json.loads(f.read_text()):
                        m.add(y, [lo, lo, hi])
                print(f"scroll box {H}px, map has {len(m.pts)} known positions")

                def shoot(page, fr, ys, tag):
                    files, yy = [], []
                    for i, y in enumerate(ys):
                        if left() <= 0:
                            print("time budget reached")
                            break
                        fr.evaluate("y => window.__sc.scrollTop = y", float(y))
                        page.wait_for_timeout(900)
                        f = str(tmp / f"{tag}_{i:03d}.png")
                        page.screenshot(path=f)
                        files.append(f)
                        yy.append(y)
                    return files, yy

                if len(m.pts) < 20:      # shards left no positions (mouse-scroll mode): look around first
                    cal = [min(max(0, H * i / 12), max(0, H - C)) for i in range(13)]
                    files, yy = shoot(pg, frame, cal, "cal")
                    per = read(files, ("sharp",)) if files else {}
                    for f, y in zip(files, yy):
                        m.add(y, per.get(f, []))

                for rnd, (dpr, modes) in enumerate([(2, ("sharp", "t150")), (2, ("sharp", "up")), (3, ("sharp", "t150"))], 1):
                    still = [n for n in mine_nums if n not in got()]
                    if not still or left() <= 0:
                        break
                    if dpr == 3:         # last try: sharper browser rendering, only for what is still missing
                        pg, frame, info3 = open_page(br, 3, link)
                        if not info3:
                            break
                    ys = sorted(set(round(y) for c in clusters(still) for y in plan(m, c)))
                    print(f"round {rnd}: {len(still)} numbers still missing {still[:20]}; {len(ys)} screenshots (scale {dpr})")
                    files, yy = shoot(pg, frame, ys, f"r{rnd}")
                    if not files:
                        break
                    per = read(files, modes)
                    for f, y in zip(files, yy):
                        m.add(y, per.get(f, []))
                    print(f"round {rnd} done at {time.time() - T0:.0f}s")
                br.close()
        except Exception:
            traceback.print_exc()
    dump = lambda rs: json.dumps([{str(k): v for k, v in r.items()} for r in rs])
    (WORK / f"reads_fill{me}.json").write_text(dump(reads))
    (WORK / f"loose_fill{me}.json").write_text(dump(loose))
    left_over = [n for n in mine_nums if n not in got()]
    print(f"filled {len(mine_nums) - len(left_over)} of {len(mine_nums)}; still missing {len(left_over)} {left_over[:30]}  ({time.time() - T0:.0f}s)")


if __name__ == "__main__":
    main()
