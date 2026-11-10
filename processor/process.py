"""Runs in GitHub Actions. Input env: URL, DETECTED_AT (ms)."""
import hashlib, io, json, os, re, subprocess, sys, time
from multiprocessing import Pool
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
HDR = {"User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TITLE = re.compile(rf"^(?P<m>{MONTHS})\s+(?P<y>20\d\d)\s+(?P<exam>.+?)\s+(?:Computer[- ]Based\s+)?Licen[sc]ure", re.I)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
now_ms = lambda: int(time.time() * 1000)


def tg(text):
    t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if t and c:
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=20)


def parse_names(text, announced=None, prefix=True):
    """prefix=True: only the unbroken 1..N run (clean text). prefix=False: keep all found (OCR may miss a few)."""
    flat = re.sub(r"\s+", " ", re.sub(r"page\s*\d+(\s*(of|/)\s*\d+)?", " ", text, flags=re.I))
    cap = int(announced * 1.1) + 1 if announced else 10**6
    found = {}
    for n, name in re.findall(r"(\d{1,6})\s+([A-ZÑÉÁÍÓÚ][^\d]*?,[^\d]*?)(?=\s+\d{1,6}\b|\s*$)", flat):
        if 1 <= int(n) <= cap:
            found.setdefault(int(n), name.strip(" ."))
    if not prefix:
        return [[n, found[n]] for n in sorted(found)]
    rows, n = [], 1
    while n in found:
        rows.append([n, found[n]]); n += 1
    return rows


enough = lambda rows, passed: bool(rows) and (not passed or len(rows) / passed >= CFG["min_match"])


def article(url):
    soup = BeautifulSoup(requests.get(url, headers=HDR, timeout=40).text, "html.parser")
    title = (soup.title.string or "").split("|")[0].strip()
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    a = re.search(r"([\d,]+)\s+out of\s+([\d,]+)\s+passed", body, re.I)
    link = next((x["href"] for x in soup.find_all("a", href=True)
                 if re.search(r"(list|roll) of successful", x.get_text(" ", strip=True), re.I)), None)
    return title, (int(a.group(1).replace(",", "")) if a else None), (int(a.group(2).replace(",", "")) if a else None), link


def drive_id(link):
    m = re.search(r"/d/([\w-]+)", link) or re.search(r"[?&]id=([\w-]+)", link)
    return m.group(1) if m else None


def try_download(link):
    fid = drive_id(link)
    urls = ([f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
             f"https://drive.google.com/uc?export=download&id={fid}"] if fid else [link])
    for u in urls:
        b = requests.get(u, headers=HDR, timeout=120).content
        if b[:5] == b"%PDF-":
            return b
        print("DRIVE SAID:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b.decode("utf8", "ignore")))[:300])
    return None


def extract(raw, passed):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        rows = parse_names("\n".join(p.extract_text() or "" for p in pdf.pages), passed)
    if enough(rows, passed):
        return rows, "text"
    Path("in.pdf").write_bytes(raw)
    subprocess.run("which ocrmypdf || sudo apt-get install -y -qq ocrmypdf tesseract-ocr", shell=True, check=True)
    subprocess.run(["ocrmypdf", "--force-ocr", "--jobs", "4", "--sidecar", "out.txt", "in.pdf", "out.pdf"], check=True)
    return parse_names(Path("out.txt").read_text(encoding="utf-8"), passed, prefix=False), "ocr"


def _ocr(f):
    return subprocess.run(["tesseract", f, "-", "--psm", "6"], capture_output=True, text=True).stdout


def screenshot_names(link, passed):
    """Open Drive's viewer, scroll + screenshot, OCR all shots in parallel (shards across CPU cores)."""
    fid = drive_id(link)
    subprocess.run("pip install -q playwright && playwright install --with-deps chromium && "
                   "(which tesseract || sudo apt-get install -y -qq tesseract-ocr)", shell=True, check=True)
    from playwright.sync_api import sync_playwright
    files, last, same = [], None, 0
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1300, "height": 1800})
        pg.goto(f"https://drive.google.com/file/d/{fid}/preview", wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(4000)
        for i in range(400):
            img = pg.screenshot(); h = hashlib.md5(img).hexdigest()
            same = same + 1 if h == last else 0; last = h
            if same >= 2:
                break
            f = f"shot{i:03d}.png"; Path(f).write_bytes(img); files.append(f)
            pg.mouse.move(650, 900); pg.mouse.wheel(0, 1300); pg.wait_for_timeout(700)
        br.close()
    print("screenshots:", len(files))
    with Pool(os.cpu_count() or 2) as pool:
        texts = pool.map(_ocr, files)
    return parse_names("\n".join(texts), passed, prefix=False)


def get_rows(link, passed):
    deadline, shots = time.time() + 20 * 60, 0
    while True:
        raw = try_download(link)
        if raw:
            rows, how = extract(raw, passed)
            if enough(rows, passed):
                return rows, how
        elif shots < 3:
            shots += 1
            if shots == 1:
                tg("⚠️ Drive blocked the PDF download. Trying screenshot + OCR…")
            try:
                rows = screenshot_names(link, passed)
                print("screenshot rows:", len(rows), "of", passed)
                if enough(rows, passed):
                    return rows, "screenshot"
            except Exception as e:
                print("screenshot failed:", repr(e))
        if time.time() > deadline:
            return [], "failed"
        time.sleep(30)


def main():
    url, detected = os.environ["URL"], int(os.environ.get("DETECTED_AT") or now_ms())
    title, passed, total, link = article(url)
    m = TITLE.match(title)
    if not m:
        print("not an exam article:", title); return
    month, year, exam = m["m"].title(), int(m["y"]), m["exam"].strip()
    sl = slug(f"{month}-{year}-{exam}")
    state_f = DATA / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"upcoming": []}
    low = title.lower()
    if "result" not in low:
        if "schedule" in low or "room assignment" in low:
            if not (DATA / f"{sl}.json").exists() and sl not in [u["slug"] for u in state["upcoming"]]:
                state["upcoming"].append(dict(slug=sl, exam=exam, month=month, year=year, title=title, url=url))
                state_f.write_text(json.dumps(state, indent=1)); print("upcoming added", sl)
        return
    deadline = time.time() + 20 * 60
    while not link and time.time() < deadline:
        time.sleep(10); title, passed, total, link = article(url)
    if not link:
        tg(f"⚠️ {title}: official list link not found after 20 min"); sys.exit(1)
    rows, how = get_rows(link, passed)
    if not enough(rows, passed):
        tg(f"🚨 {title}\nGot {len(rows)} of {passed}. Needs a manual look."); sys.exit(1)
    meta = dict(slug=sl, exam=exam, month=month, year=year, title=title, source=url, passed=passed, examinees=total,
                count=len(rows), method=how, updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    (DATA / f"{sl}.json").write_text(json.dumps({"meta": meta, "passers": rows}, ensure_ascii=False, separators=(",", ":")))
    state["upcoming"] = [u for u in state["upcoming"] if u["slug"] != sl]
    state_f.write_text(json.dumps(state, indent=1))
    (DATA / "pending.json").write_text(json.dumps(dict(meta, detected_at=detected, built_at=now_ms())))
    print("built", sl, len(rows), how)


if __name__ == "__main__":
    main()
