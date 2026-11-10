import json, os, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
WORK = ROOT / "work"; WORK.mkdir(exist_ok=True)
HDR = {"User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TITLE = re.compile(rf"^(?P<m>{MONTHS})\s+(?P<y>20\d\d)\s+(?P<exam>.+?)\s+(?:Computer[- ]Based\s+)?Licen[sc]ure", re.I)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
now_ms = lambda: int(time.time() * 1000)


def tg(text):
    t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if t and c:
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=20)


def out(**kw):
    f = os.environ.get("GITHUB_OUTPUT")
    for k, v in kw.items():
        print(f"{k}={v}")
        if f:
            open(f, "a").write(f"{k}={v}\n")


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


FIX = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I", "!": "I", "_": " ", "’": "'", "`": "'", "—": "-"})
NAME_OK = re.compile(r"^[A-ZÑÉÁÍÓÚÜ][A-ZÑÉÁÍÓÚÜ .'\-]*, [A-ZÑÉÁÍÓÚÜ][A-ZÑÉÁÍÓÚÜ .'\-]*$")


def clean(name):
    n = name.upper().translate(FIX)
    n = re.sub(r"[^A-ZÑÉÁÍÓÚÜ.,'\- ]", "", n)
    n = re.sub(r"\s*,\s*", ", ", n)
    return re.sub(r"\s+", " ", n).strip(" -")


def parse_rows(text, announced=None):
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    for line in text.splitlines():
        m = re.match(r"^\W*?(\d{1,6})\s+(.+)$", line.strip())
        if not m:
            continue
        n, name = int(m[1]), clean(m[2])
        if 1 <= n <= cap and "," in name and len(name) > 4 and n not in rows:
            rows[n] = name
    return rows


def parse_flat(text, announced=None):
    flat = re.sub(r"\s+", " ", re.sub(r"page\s*:?\s*\d+(\s*(of|/)\s*\d+)?", " ", text, flags=re.I))
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    for n, name in re.findall(r"(\d{1,6})\s+([A-ZÑÉÁÍÓÚ][^\d]*?,[^\d]*?)(?=\s+\d{1,6}\b|\s*$)", flat):
        if 1 <= int(n) <= cap:
            rows.setdefault(int(n), clean(name))
    return rows


def complete(rows, passed):
    n = passed or max(rows, default=0)
    return n > 0 and all(i in rows for i in range(1, n + 1))
