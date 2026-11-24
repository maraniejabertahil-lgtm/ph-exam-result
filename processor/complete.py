"""Second pipeline, stage 2: page images. Same stages as pipeline 1 (process.yml):

  plan              page positions of the list viewer                (prepare job)   -> work/plan.json
                    + how many shard jobs this list needs            (outputs total and matrix)
  shard N T         capture this shard's slice of the pages          (shards)        -> work/captures/
  check             which pages nobody captured                      (gaps)          -> work/missing.json
  fill N K          capture this fill job's share of the missing     (fill)
  finish            merge, drop repeats, save to scans/<slug>/       (finish)
  extras            schools and top-notchers pages, saved to scans   (extras)
  wait              late links only: wait until pipeline 1 has saved the release (add-links workflow)

No OCR and no text reading. The Drive viewer is opened the same way as in pipeline 1 (ocr.FIND, ocr.launch).
Each saved WebP holds one complete official page cropped cleanly to the white paper (no viewer bars or dark sides).

Late links (add-links workflow): "extras" runs with ONLY_MISSING=1, so a page that is already saved is not
captured again, and it reports what it saved through the outputs "slug" and "saved"."""
import hashlib, io, json, math, os, shutil, subprocess, sys, time
from pathlib import Path

from PIL import Image

from common import out, tg
from ocr import launch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
SCANS = ROOT / "scans"
WORK = HERE / "work"
CAP = WORK / "captures"
VW, VH, DPR = 1200, 2000, 2
STEP = 0.9          # fallback step when page boxes cannot be read
MAX_VIEWS = 250     # maximum pages captured per document
WAIT = 1100         # ms to let each view paint
PER_FILL_JOB = 10
MAX_FILL_JOBS = 20
VIEWS_PER_SHARD = 8   # a small list gets 1 or 2 shard jobs instead of 20 (each job costs about a minute of set-up)
MAX_SHARDS = 20
WAIT_TRIES = 40       # late links: 40 tries x 30 seconds = 20 minutes at most
WORK.mkdir(parents=True, exist_ok=True)

HIDE_UI_JS = """() => {
  if (!document.getElementById('__ph_clean')) {
    const st = document.createElement('style');
    st.id = '__ph_clean';
    st.textContent = '::-webkit-scrollbar{display:none!important}[role="toolbar"]{display:none!important}';
    (document.head || document.documentElement).appendChild(st);
  }
  for (const el of document.querySelectorAll('div,button,a')) {
    if (el.querySelector('img,canvas')) continue;
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const txt = (el.innerText || '').trim();
    const aria = (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('data-tooltip') || '');
    const topRightBtn = r.width <= 96 && r.height <= 96 && r.top < 140 && r.right > window.innerWidth - 140;
    const bottomPill = r.bottom > window.innerHeight - 140 && r.height <= 100 && r.width <= 600;
    if (/^Page\\s+\\d+\\s*\\/\\s*\\d+/i.test(txt) || /pop-out|open in new|zoom|toolbar/i.test(aria) || topRightBtn || bottomPill) {
      el.style.setProperty('display', 'none', 'important');
    }
  }
}"""

PAGES_JS = """() => {
  const sc = window.__sc;
  const st = sc ? sc.scrollTop : 0;
  let els = [...document.querySelectorAll('img')].filter(im =>
    (im.src && im.src.startsWith('blob:')) || /page\\s+\\d+/i.test(im.alt || '')
  );
  if (!els.length) els = [...document.querySelectorAll('canvas')];
  const pages = [];
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 200) continue;
    const m = (el.alt || '').match(/page\\s+(\\d+)/i);
    const pageNum = m ? parseInt(m[1], 10) : null;
    const ready = el.tagName === 'IMG' ? (el.complete && el.naturalWidth > 0) : true;
    pages.push({
      pageNum,
      ready,
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
      docTop: st + r.top,
    });
  }
  pages.sort((a, b) => a.docTop - b.docTop);
  return {
    st,
    vh: window.innerHeight,
    h: sc ? sc.scrollHeight : document.documentElement.scrollHeight,
    c: sc ? sc.clientHeight : window.innerHeight,
    pages,
  };
}"""


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


def save_webp(png, path, trim_paper=True):
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if trim_paper:
        box = im.convert("L").point(lambda p: 255 if p > 235 else 0).getbbox()
        if box:
            bw, bh = box[2] - box[0], box[3] - box[1]
            # Crop out Drive's dark viewer margins/shadows while protecting real page content.
            if bw >= im.width * 0.45 and bh >= im.height * 0.45:
                im = im.crop(box)
    im.save(path, "WEBP", lossless=True, quality=100, method=6)


def hide_ui(pg, fr):
    for target in (fr, pg):
        try:
            target.evaluate(HIDE_UI_JS)
        except Exception:
            pass


FIND_VIEWER = """() => {
  let b = null, m = 0;
  for (const e of document.querySelectorAll('*')) {
    if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
    if (e.scrollHeight > e.clientHeight + 200 && e.scrollHeight > m) { m = e.scrollHeight; b = e; }
  }
  if (!b && document.scrollingElement && document.scrollingElement.scrollHeight > window.innerHeight + 200) {
    b = document.scrollingElement;
  }
  if (!b) {
    const pages = [...document.querySelectorAll('img,canvas')].filter(el => {
      if (el.tagName === 'IMG') {
        const okSrc = (el.src && el.src.startsWith('blob:')) || /page\\s+\\d+/i.test(el.alt || '');
        if (!okSrc || !el.complete || el.naturalWidth <= 0) return false;
      }
      const r = el.getBoundingClientRect();
      return r.width >= 200 && r.height >= 200;
    });
    if (!pages.length) return null;
    let cur = pages[0].parentElement;
    while (cur && cur !== document.body) {
      if (/(auto|scroll)/.test(getComputedStyle(cur).overflowY) && cur.clientHeight >= 200) { b = cur; break; }
      cur = cur.parentElement;
    }
    if (!b) b = document.scrollingElement || document.documentElement || document.body;
  }
  if (!b) return null;
  window.__sc = b;
  return { h: b.scrollHeight || window.innerHeight, c: b.clientHeight || window.innerHeight };
}"""


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
                info = fr.evaluate(FIND_VIEWER)
            except Exception:
                info = None
            if info:
                pg.wait_for_timeout(2000)
                hide_ui(pg, fr)
                return pg, fr, info
    return pg, None, None


def positions(H, C):
    """Fallback scroll positions when page boxes cannot be read."""
    last = max(0, H - C)
    if last == 0:
        return [0]
    step = max(STEP * C, last / (MAX_VIEWS - 1))
    n = math.ceil(last / step) + 1
    return [round(min(last, k * step)) for k in range(n)]


def build_plan(pg, fr, info):
    """Find every PDF page's vertical position so each screenshot holds one complete, uncut page."""
    H, C = info["h"], info["c"]
    try:
        snap = fr.evaluate(PAGES_JS)
    except Exception:
        snap = None
    pages = (snap or {}).get("pages") or []
    if len(pages) == 1 and H > C * 1.15:
        try:
            fr.evaluate("y => window.__sc.scrollTop = y", float(round(pages[0]["height"] * 0.75)))
            pg.wait_for_timeout(1000)
            snap2 = fr.evaluate(PAGES_JS)
            if snap2 and len(snap2.get("pages") or []) >= 2:
                pages = snap2["pages"]
            fr.evaluate("window.__sc.scrollTop = 0")
            pg.wait_for_timeout(400)
        except Exception:
            pass
    if len(pages) >= 2:
        p0, p1 = pages[0], pages[1]
        top0 = max(0.0, p0["docTop"])
        page_h = p0["height"]
        pitch = p1["docTop"] - p0["docTop"]
        if pitch > 200:
            n = max(1, min(MAX_VIEWS, round((H - top0 - page_h) / pitch) + 1))
            ys = [round(top0 + k * pitch) for k in range(n)]
            return {"H": H, "C": C, "ys": ys, "page_h": round(page_h), "mode": "pages"}
    if len(pages) == 1:
        return {"H": H, "C": C, "ys": [round(max(0.0, pages[0]["docTop"]))], "page_h": round(pages[0]["height"]), "mode": "pages"}
    return {"H": H, "C": C, "ys": positions(H, C), "mode": "scroll"}


def frame_offset(pg, fr):
    if fr == pg.main_frame:
        return 0.0, 0.0
    try:
        box = fr.frame_element().bounding_box()
        if box:
            return float(box["x"]), float(box["y"])
    except Exception:
        pass
    return 0.0, 0.0


def pick_page(pages, idx, y_target):
    if not pages:
        return None
    for p in pages:
        if p.get("pageNum") == idx + 1:
            return p
    return min(pages, key=lambda p: abs(p["docTop"] - y_target))


def grab(pg, fr, plan, idxs, folder):
    folder.mkdir(parents=True, exist_ok=True)
    ys = plan["ys"]
    page_mode = plan.get("mode") == "pages"
    cur_vh = VH
    for idx in idxs:
        try:
            y_target = float(ys[idx])
            scroll_to = max(0.0, y_target - 12.0) if page_mode else y_target
            fr.evaluate("y => window.__sc.scrollTop = y", scroll_to)
            pg.wait_for_timeout(WAIT)
            target = None
            if page_mode:
                for _ in range(5):
                    hide_ui(pg, fr)
                    snap = fr.evaluate(PAGES_JS)
                    target = pick_page((snap or {}).get("pages") or [], idx, y_target)
                    if target and target.get("ready"):
                        break
                    pg.wait_for_timeout(450)
                if target:
                    need_vh = math.ceil(target["height"]) + 60
                    if need_vh > cur_vh:
                        cur_vh = need_vh
                        pg.set_viewport_size({"width": VW, "height": cur_vh})
                        pg.wait_for_timeout(300)
                        snap = fr.evaluate(PAGES_JS)
                        target = pick_page((snap or {}).get("pages") or [], idx, y_target)
                    if target and (target["top"] < 0 or target["top"] + target["height"] > cur_vh):
                        adj = max(0.0, float((snap or {}).get("st", scroll_to)) + target["top"] - 12.0)
                        fr.evaluate("y => window.__sc.scrollTop = y", adj)
                        pg.wait_for_timeout(450)
                        hide_ui(pg, fr)
                        snap = fr.evaluate(PAGES_JS)
                        target = pick_page((snap or {}).get("pages") or [], idx, y_target)
            hide_ui(pg, fr)
            if target and target["width"] >= 200 and target["height"] >= 200:
                fx, fy = frame_offset(pg, fr)
                x = max(0.0, fx + target["left"])
                y = max(0.0, fy + target["top"])
                w = min(float(VW) - x, float(target["width"]))
                h = min(float(cur_vh) - y, float(target["height"]))
                if w >= 200 and h >= 200:
                    png = pg.screenshot(clip={"x": x, "y": y, "width": w, "height": h})
                    save_webp(png, folder / f"v{idx:04d}.webp", trim_paper=True)
                    continue
            save_webp(pg.screenshot(), folder / f"v{idx:04d}.webp", trim_paper=True)
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
            grab(pg, frame, plan, idxs, CAP)
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
            plan = build_plan(pg, frame, info)
            plan["did"] = did
        finally:
            br.close()
    (WORK / "plan.json").write_text(json.dumps(plan))
    shards = shard_count(len(plan["ys"]))
    print(f"plan ({plan.get('mode')}): {len(plan['ys'])} page(s), scroll box {plan['H']}px, visible {plan['C']}px, {shards} shard job(s)")
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


def cmd_wait():
    """Late links: PRC added a schools / top-10 link while pipeline 1 may still be running.
    Wait (up to 20 minutes) until pipeline 1 has saved the release for this article, then carry on."""
    article = load("links.json")["article"]
    for attempt in range(1, WAIT_TRIES + 1):
        if any(d["meta"].get("source") == article for _, d in releases()):
            print("the release for this article is saved: continuing")
            return
        print(f"release not saved yet (try {attempt}/{WAIT_TRIES}); waiting 30 seconds")
        time.sleep(30)
        subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=ROOT, check=False)
    print("no release for this article after 20 minutes: nothing to add the pages to")
    sys.exit(1)


def cmd_extras():
    from playwright.sync_api import sync_playwright
    only_missing = os.environ.get("ONLY_MISSING") == "1"
    links = load("links.json")
    article = links["article"]
    rel = [(p, d) for p, d in releases() if d["meta"].get("source") == article]
    if not rel:
        print("no release matches this article yet")
        out(saved="")
        return
    saved = []
    for kind in ("schools", "topnotchers"):
        dids = links["links"].get(kind) or []
        if not dids:
            print(f"no {kind} link on the article")
            continue
        if only_missing and all(d["meta"].get(f"{kind}_scans") for _, d in rel):
            print(f"{kind}: already saved, skipped")
            continue
        tmp = WORK / "extras" / kind
        with sync_playwright() as p:
            br = launch(p)
            try:
                pg, frame, info = open_page(br, dids[0])
                if not frame:
                    print(f"{kind}: viewer not found")
                    continue
                plan = build_plan(pg, frame, info)
                grab(pg, frame, plan, list(range(len(plan["ys"]))), tmp)
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
        saved.append(kind)
    out(slug=rel[0][1]["meta"]["slug"], saved=",".join(saved))


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
    elif cmd == "wait":
        cmd_wait()
    else:
        sys.exit(f"unknown command: {cmd!r}")
