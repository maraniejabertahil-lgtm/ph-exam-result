"""Runs in GitHub Actions (free). Input env: URL, DETECTED_AT (ms). Handles results + schedule articles."""
import io, json, os, re, subprocess, sys, time
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
    if t and c: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=20)


def parse_names(text, announced=None):
    flat = re.sub(r"\s+", " ", re.sub(r"page\s*\d+(\s*(of|/)\s*\d+)?", " ", text, flags=re.I))
    cap = int(announced * 1.1) + 1 if announced else 10**6
    found = {}
    for n, name in re.findall(r"(\d{1,6})\s+([A-ZÑÉÁÍÓÚ][^\d]*?,[^\d]*?)(?=\s+\d{1,6}\b|\s*$)", flat):
        if 1 <= int(n) <= cap: found.setdefault(int(n), name.strip(" ."))
    rows, n = [], 1
    while n in found: rows.append([n, found[n]]); n += 1
    return rows


def article(url):
    soup = BeautifulSoup(requests.get(url, headers=HDR, timeout=40).text, "html.parser")
    title = (soup.title.string or "").split("|")[0].strip()
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    a = re.search(r"([\d,]+)\s+out of\s+([\d,]+)\s+passed", body, re.I)
    link = next((x["href"] for x in soup.find_all("a", href=True) if re.search(r"(list|roll) of successful", x.get_text(" ", strip=True), re.I)), None)
    return title, (int(a.group(1).replace(",", "")) if a else None), (int(a.group(2).replace(",", "")) if a else None), link


def get_pdf(link):
    fid = (re.search(r"/d/([\w-]+)", link) or re.search(r"[?&]id=([\w-]+)", link)).group(1)
    b = requests.get(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t", headers=HDR, timeout=120).content
    if b[:5] != b"%PDF-": raise RuntimeError("Drive did not return a PDF")
    return b


def extract(raw, passed):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        rows = parse_names("\n".join(p.extract_text() or "" for p in pdf.pages), passed)
    if passed and len(rows) / passed >= CFG["min_match"]: return rows, "text"
    Path("in.pdf").write_bytes(raw)   # scanned / odd layout -> OCR (installed only when needed)
    subprocess.run("which ocrmypdf || sudo apt-get install -y -qq ocrmypdf tesseract-ocr", shell=True, check=True)
    subprocess.run(["ocrmypdf", "--force-ocr", "--jobs", "4", "--sidecar", "out.txt", "in.pdf", "out.pdf"], check=True)
    rows2 = parse_names(Path("out.txt").read_text(encoding="utf-8"), passed)
    return (rows2 if len(rows2) > len(rows) else rows), "ocr"


def main():
    url, detected = os.environ["URL"], int(os.environ.get("DETECTED_AT") or now_ms())
    title, passed, total, link = article(url)
    m = TITLE.match(title)
    if not m: print("not an exam article:", title); return
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
    deadline = time.time() + 20 * 60                      # PRC sometimes posts the list link a bit later
    while not link and time.time() < deadline:
        time.sleep(10); title, passed, total, link = article(url)
    if not link: tg(f"⚠️ {title}: official list link not found after 20 min"); sys.exit(1)
    rows, how = extract(get_pdf(link), passed)
    if not rows or (passed and len(rows) / passed < CFG["min_match"]):
        tg(f"🚨 {title}\nParsed {len(rows)} of {passed}. Needs a manual look."); sys.exit(1)
    meta = dict(slug=sl, exam=exam, month=month, year=year, title=title, source=url, passed=passed, examinees=total,
                count=len(rows), method=how, updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    (DATA / f"{sl}.json").write_text(json.dumps({"meta": meta, "passers": rows}, ensure_ascii=False, separators=(",", ":")))
    state["upcoming"] = [u for u in state["upcoming"] if u["slug"] != sl]
    state_f.write_text(json.dumps(state, indent=1))
    (DATA / "pending.json").write_text(json.dumps(dict(meta, detected_at=detected, built_at=now_ms())))
    print("built", sl, len(rows), how)


if __name__ == "__main__":
    main()
