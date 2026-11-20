"""Second pipeline, stage 2: page images. Same stages as pipeline 1 (process.yml):

  plan              scroll positions of the list viewer              (prepare job)   -> work/plan.json
                    + how many shard jobs this list needs            (outputs total and matrix)
  shard N T         capture this shard's slice of the positions      (shards)        -> work/captures/
  check             which positions nobody captured                  (gaps)          -> work/missing.json
  fill N K          capture this fill job's share of the missing     (fill)
  finish            merge, drop repeats, save to scans/<slug>/       (finish)
  extras            schools and top-notchers pages, saved to scans   (extras)

No OCR and no text reading. The Drive viewer is opened the same way as in pipeline 1 (ocr.FIND, ocr.launch)."""
import hashlib, io, json, math, shutil, sys
from pathlib import Path

from PIL import Image

from common import out, tg
from ocr import FIND, launch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
SCANS = ROOT / "scans"
WORK = HERE / "work"
CAP = WORK / "captures"
VW, VH, DPR = 1200, 1600, 2
STEP = 0.9          # each new view overlaps the last one by 10%
MAX_VIEWS = 150     # same cap as before
WAIT = 1100         # ms to let each view paint
PER_FILL_JOB = 10
MAX_FILL_JOBS = 20
VIEWS_PER_SHARD = 8   # a small list gets 1 or 2 shard jobs instead of 20 (each job costs about a minute of set-up)
MAX_SHARDS = 20
WORK.mkdir(parents=True, exist_ok=True)


def load(name):
    return json.loads((WORK / name).read_text())


def releases():
    out_list = []
    for p in DATA.glob("*.json"):
        if p.stem in ("state", "releases"):
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("meta"), dict):
            out_list.append((p, d))
    return out_list


def save_webp(png, path):
    Image.open(io.BytesIO(png)).convert("RGB").save(path, "WEBP", lossless=True, quality=100, method=6)


def open_page(br, did, dpr=DPR):
    pg = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=dpr)
    pg.set_default_timeout(20000)
    try:
        pg.goto(f"https://drive.google.com/file/d/{did}/preview", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print("page load problem (continuing):", str(e)[:200])
    for _ in range(30):
        pg.wait_for_timeout(700)
        for fr in pg.frames:
            try:
                info = fr.evaluate(FIND)
            except Exception:
                info = None
            if info:
                pg.wait_for_timeout(2000)
                return pg, fr, info
    return pg, None, None


def positions(H, C):
    """Scroll positions from the top to the bottom, last one included, at most MAX_VIEWS."""
    last = max(0, H - C)
    if last == 0:
        return [0]
    step = max(STEP * C, last / (MAX_VIEWS - 1))
    n = math.ceil(last / step) + 1
    return [round(min(last, k * step)) for k in range(n)]


def grab(pg, frame, ys, idxs, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for idx in idxs:
        try:
            frame.evaluate("y => window.__sc.scrollTop = y", float(ys[idx]))
            pg.wait_for_timeout(WAIT)
            save_webp(pg.screenshot(), folder / f"v{idx:04d}.webp")
        except Exception as e:
            print(f"view {idx} failed: {str(e)[:150]}")


def capture(idxs):
    """Open the names list and capture only the given view numbers into work/captures/."""
    from playwright.sync_api import sync_playwright
    if not idxs:
        print("nothing to capture")
        return
    plan = load("plan.json")
    with sync_playwright() as p:
        br = launch(p)
        try:
            pg, frame, _ = open_page(br, plan["did"])
            if not frame:
                print("viewer not found; nothing captured")
                return
            grab(pg, frame, plan["ys"], idxs, CAP)
        finally:
            br.close()


def unique(files):
    """Keep the first of every identical picture, in view order."""
    seen, keep = set(), []
    for f in sorted(files, key=lambda p: int(p.stem[1:])):
        h = hashlib.md5(f.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            keep.append(f)
    return keep


def captured_numbers():
    return {int(p.stem[1:]) for p in CAP.glob("v*.webp")} if CAP.exists() else set()


def shard_count(views):
    """How many shard jobs a list with this many views needs (1 to MAX_SHARDS)."""
    return max(1, min(MAX_SHARDS, math.ceil(views / VIEWS_PER_SHARD)))


def cmd_plan():
    from playwright.sync_api import sync_playwright
    links = load("links.json")
    names = links["links"].get("names") or []
    if not names:
        print("no names link on the article")
        sys.exit(1)
    did = names[0]
    with sync_playwright() as p:
        br = launch(p)
        try:
            pg, frame, info = open_page(br, did)
            if not frame:
                print("viewer not found")
                sys.exit(1)
            H, C = info["h"], info["c"]
            ys = positions(H, C)
        finally:
            br.close()
    (WORK / "plan.json").write_text(json.dumps({"did": did, "H": H, "C": C, "ys": ys}))
    shards = shard_count(len(ys))
    print(f"plan: {len(ys)} views, scroll box {H}px, visible {C}px, {shards} shard job(s)")
    out(total=shards, matrix=json.dumps(list(range(shards))))


def cmd_shard(i, T):
    plan = load("plan.json")
    n = len(plan["ys"])
    idxs = list(range(i * n // T, (i + 1) * n // T))
    print(f"shard {i}/{T}: views {idxs[:1]}..{idxs[-1:]} ({len(idxs)})")
    capture(idxs)


def cmd_check():
    plan = load("plan.json")
    total = len(plan["ys"])
    have = captured_numbers()
    missing = [i for i in range(total) if i not in have]
    (WORK / "missing.json").write_text(json.dumps(missing))
    k = min(MAX_FILL_JOBS, math.ceil(len(missing) / PER_FILL_JOB)) if missing else 0
    print(f"views {total}, captured {total - len(missing)}, missing {len(missing)} {missing[:30]}")
    out(need="yes" if missing else "no", k=k, matrix=json.dumps(list(range(k))))


def cmd_fill(me, K):
    missing = load("missing.json")
    mine = missing[me::K]
    print(f"fill {me + 1}/{K}: {len(mine)} views {mine}")
    capture(mine)


def cmd_finish():
    plan = load("plan.json")
    links = load("links.json")
    article = links["article"]
    have = captured_numbers()
    gaps = [i for i in range(len(plan["ys"])) if i not in have]
    keep = unique(list(CAP.glob("v*.webp")))
    if not keep:
        print("no page images captured")
        sys.exit(1)
    rel = [(p, d) for p, d in releases() if d["meta"].get("source") == article]
    if not rel:
        print("no release matches this article yet")
        sys.exit(1)
    for p, d in rel:
        m = d["meta"]
        folder = SCANS / m["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("names-*.webp"):
            old.unlink()
        names = []
        for n, f in enumerate(keep, 1):
            name = f"names-{n:03d}.webp"
            shutil.copy(f, folder / name)
            names.append(f"/scans/{m['slug']}/{name}")
        m["scans"] = names
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        print(f"{m['slug']}: {len(names)} page images")
    first = rel[0][1]["meta"]
    out(slug=first["slug"])
    if gaps:
        tg(f"⚠️ {first['title']}: {len(gaps)} page position(s) still not captured: views {gaps[:30]}.")


def cmd_extras():
    from playwright.sync_api import sync_playwright
    links = load("links.json")
    article = links["article"]
    rel = [(p, d) for p, d in releases() if d["meta"].get("source") == article]
    if not rel:
        print("no release matches this article yet")
        return
    for kind in ("schools", "topnotchers"):
        dids = links["links"].get(kind) or []
        if not dids:
            print(f"no {kind} link on the article")
            continue
        tmp = WORK / "extras" / kind
        with sync_playwright() as p:
            br = launch(p)
            try:
                pg, frame, info = open_page(br, dids[0])
                if not frame:
                    print(f"{kind}: viewer not found")
                    continue
                ys = positions(info["h"], info["c"])
                grab(pg, frame, ys, list(range(len(ys))), tmp)
            finally:
                br.close()
        keep = unique(list(tmp.glob("v*.webp"))) if tmp.exists() else []
        if not keep:
            print(f"{kind}: no page images captured")
            continue
        for p2, d in rel:
            m = d["meta"]
            folder = SCANS / m["slug"]
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(f"{kind}-*.webp"):
                old.unlink()
            names = []
            for n, f in enumerate(keep, 1):
                name = f"{kind}-{n:03d}.webp"
                shutil.copy(f, folder / name)
                names.append(f"/scans/{m['slug']}/{name}")
            m[f"{kind}_scans"] = names
            p2.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        print(f"{kind}: {len(keep)} page images saved")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "plan":
        cmd_plan()
    elif cmd == "shard":
        cmd_shard(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "check":
        cmd_check()
    elif cmd == "fill":
        cmd_fill(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "finish":
        cmd_finish()
    elif cmd == "extras":
        cmd_extras()
    else:
        sys.exit(f"unknown command: {cmd!r}")
