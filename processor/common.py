import json, os, re, subprocess, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
WORK = ROOT / "work"; WORK.mkdir(exist_ok=True)
HDR = {"User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# Accepts one month ("November 2026 ...") or several ("August and September 2026 ...", "April, May & June 2026 ...")
TITLE = re.compile(rf"^(?P<m>(?:{MONTHS})(?:\s*(?:,|&|and)\s*(?:{MONTHS}))*)\s+(?P<y>20\d\d)\s+(?P<exam>.+?)\s+(?:Computer[- ]Based\s+)?Licen[sc]ure", re.I)
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


# ---------------------------------------------------------------------------------------------
# Reading one OCR text block into {number: name}
#   * numbers are matched to names by the line they are on
#   * a number that OCR garbled into look-alike letters ("2690O", "1l5") is repaired when it fits the sequence
#   * a line whose number is missing is numbered from its neighbours (n-1 above, n+1 below)
# ---------------------------------------------------------------------------------------------
DIGIT_LOOK = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "!": "1", "i": "1",
                            "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6", "b": "6"})
_LOOK = "0-9OoQDIl|!iSsBZzGb"
RE_STRICT = re.compile(r"^\W*?(\d{1,6})[.\s]+(.+)$")          # "123 NAME"
RE_GLUED = re.compile(r"^\W*?(\d{1,6})(?=[A-ZÑ])(.+)$")       # "123NAME"
RE_LOOK = re.compile(rf"^\W*?([{_LOOK}]{{1,6}})\s+(.+)$")      # "12O NAME"
_median = lambda xs: sorted(xs)[len(xs) // 2]
good_name = lambda name: "," in name and len(name) > 4


def _split_lines(text):
    """-> list of [number or None, raw name, repaired?]"""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = RE_STRICT.match(line) or RE_GLUED.match(line)
        if m:
            items.append([int(m[1]), m[2], False]); continue
        m = RE_LOOK.match(line)
        if m and re.search(r"\d", m[1]):
            items.append([int(m[1].translate(DIGIT_LOOK)), m[2], True]); continue
        items.append([None, line, False])
    return items


LOOK = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "!": "1", "i": "1",
                      "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6"})
ABBR = re.compile(r"^(MA|JR|SR|ST|DR|MR|MS|II|III|IV|[A-Z])$")


def fix_comma(n):
    """OCR often turns the comma after the surname into a full stop or semicolon: 'FLORES. ANGELICA' -> 'FLORES, ANGELICA'."""
    if "," in n:
        return n
    m = re.match(r"^((?:[A-ZÑÉÁÍÓÚÜ'\-]+ )*?[A-ZÑÉÁÍÓÚÜ'\-]{3,})[.;:]+\s+(.+)$", n)
    if m and not ABBR.match(m.group(1).split()[-1]):
        return f"{m.group(1)}, {m.group(2)}"
    return n


def _items(text):
    """[[number, name], ...] for every line that starts with something number-like."""
    items = []
    for line in text.splitlines():
        m = re.match(r"^\W*?([0-9OolI|!SBDiZzG]{1,6})\s+(.+)$", line.strip())
        if not m or not re.search(r"\d", m[1]):        # a real number has at least one digit
            continue
        num = m[1].translate(LOOK)
        name = fix_comma(clean(m[2]))
        if num.isdigit() and len(name) > 4:
            items.append([int(num), name])
    return items


def parse_rows(text, announced=None):
    """{number: name}. A misread number is repaired from its neighbours (…102, 1O3x, 104… -> 103)."""
    cap = int(announced * 1.1) + 1 if announced else 10**6
    items = _items(text)
    for i, it in enumerate(items):
        prev = items[i - 1][0] if i else None
        nxt = items[i + 1][0] if i + 1 < len(items) else None
        if prev and nxt and nxt - prev == 2 and it[0] != prev + 1:
            it[0] = prev + 1
    rows = {}
    for n, name in items:
        if 1 <= n <= cap and "," in name and n not in rows:
            rows[n] = name
    return rows


def parse_loose(text, announced, strict):
    """Numbered lines the strict reader rejected (e.g. a name with no comma). Only used later to fill gaps."""
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    for n, name in _items(text):
        if 1 <= n <= cap and n not in strict and n not in rows and len(name) >= 3:
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
