import json, os, re, subprocess, time
from pathlib import Path
from urllib.parse import urljoin, urlparse as _urlparse
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------------------------
# GitHub NEVER contacts PRC (PRC blocks GitHub's servers). Everything about PRC comes from the Cloudflare Worker.
# If any code still tries, it stops AT ONCE with a clear message instead of hanging and retrying for minutes.
# ---------------------------------------------------------------------------------------------
class PRCBlocked(RuntimeError):
    pass


_real_request = requests.sessions.Session.request


def _guarded_request(self, method, url, *args, **kwargs):
    host = (_urlparse(str(url)).hostname or "").lower()
    if host == "prc.gov.ph" or host.endswith(".prc.gov.ph"):
        raise PRCBlocked(f"Blocked: GitHub must never contact {host}. Use the details saved by the Cloudflare Worker.")
    return _real_request(self, method, url, *args, **kwargs)


requests.sessions.Session.request = _guarded_request

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
    if os.environ.get("DRY_RUN") == "true":
        print("[DRY_RUN tg skipped]", text)
        return
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


def download_drive_pdf(link, timeout=30):
    """Download raw PDF bytes from Google Drive if downloads are allowed; returns None if view-only/unavailable."""
    fid = drive_id(link)
    if not fid:
        return None
    sess = requests.Session()
    sess.headers.update(HDR)
    urls = [
        f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
        f"https://drive.google.com/uc?export=download&id={fid}",
    ]
    for u in urls:
        try:
            r = sess.get(u, timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                continue
            if r.content[:5] == b"%PDF-":
                return r.content
            if b"<form" in r.content[:65536].lower():
                soup = BeautifulSoup(r.text, "html.parser")
                form = soup.find("form", id="download-form") or soup.find("form")
                if form and form.get("action"):
                    params = {inp["name"]: inp.get("value", "") for inp in form.find_all("input", {"name": True})}
                    r2 = sess.get(urljoin(r.url, form["action"]), params=params, timeout=timeout, allow_redirects=True)
                    if r2.status_code == 200 and r2.content[:5] == b"%PDF-":
                        return r2.content
        except Exception:
            continue
    return None


FIX = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I", "!": "I", "_": " ", "’": "'", "`": "'", "—": "-"})
NAME_OK = re.compile(r"^[A-ZÑÉÁÍÓÚÜ][A-ZÑÉÁÍÓÚÜ .'\-]*, [A-ZÑÉÁÍÓÚÜ][A-ZÑÉÁÍÓÚÜ .'\-]*$")


def clean(name):
    n = name.upper().translate(FIX)
    n = re.sub(r"[^A-ZÑÉÁÍÓÚÜ.,'\- ]", "", n)
    n = re.sub(r"\s*,\s*", ", ", n)
    return re.sub(r"\s+", " ", n).strip(" -")


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
        s = line.strip()
        m = (re.match(r"^\W*?([0-9OolI|!SBDiZzG]{1,6})\s+(.+)$", s)
             or re.match(r"^\W*?(\d{1,6})(?=[A-ZÑÉÁÍÓÚÜ])(.+)$", s)
             or re.match(r"^[A-Za-z]\W*?(\d{1,6})\s+([A-ZÑÉÁÍÓÚÜ].+,.+)$", s))
        if not m or not re.search(r"\d", m[1]):        # a real number has at least one digit
            continue
        num = m[1].translate(LOOK)
        name = fix_comma(clean(m[2]))
        if num.isdigit() and len(name) > 4:
            items.append([int(num), name])
    return items


def parse_rows(text, announced=None):
    """{number: name}. Repairs misread/missing numbers from adjacent rows (…102, 1O3x, 104… -> 103)."""
    cap = int(announced * 1.1) + 1 if announced else 10**6
    seq = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        m = (re.match(r"^\W*?([0-9OolI|!SBDiZzG]{1,6})\s+(.+)$", s)
             or re.match(r"^\W*?(\d{1,6})(?=[A-ZÑÉÁÍÓÚÜ])(.+)$", s)
             or re.match(r"^[A-Za-z]\W*?(\d{1,6})\s+([A-ZÑÉÁÍÓÚÜ].+,.+)$", s))
        if m and re.search(r"\d", m[1]):
            num = m[1].translate(LOOK)
            name = fix_comma(clean(m[2]))
            if num.isdigit() and len(name) > 4:
                seq.append([int(num), name])
            continue
        cand_name = fix_comma(clean(s))
        if "," in cand_name and len(cand_name) > 6 and not re.search(
            r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER|NOTHING FOLLOWS|PAGE:|ROLL OF)",
            cand_name,
        ):
            seq.append([None, cand_name])
    for i, it in enumerate(seq):
        if it[0] is None:
            prev = seq[i - 1][0] if i and seq[i - 1][0] is not None else None
            nxt = seq[i + 1][0] if i + 1 < len(seq) and seq[i + 1][0] is not None else None
            if prev is not None and nxt is not None and nxt - prev == 2:
                it[0] = prev + 1
    items = [it for it in seq if it[0] is not None]
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


def parse_pdf_text(text, announced=None):
    """Extract {number: name} verbatim from selectable PDF text (supports 1-col and multi-col, strips footers)."""
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    text = re.split(r"NOTHING\s+FOLLOWS", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"(?m)^(\s*\d{1,6})\s*\r?\n\s*([^\W\d_])", r"\1 \2", text)
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or re.search(r"^(Roll of Successful|Held on\b|Released on\b|Page\s*:|Seq\.?\s*No\.?\b)", line, re.I):
            continue
        if re.search(r"\bLICENSURE\s+EXAMINATION\b", line, re.I) and "," not in line:
            continue
        matches = re.findall(
            r"(?:^|\s)(\d{1,6})\s+([^\W\d_].+?)(?=\s+\d{1,6}\s+[^\W\d_]|$)",
            line,
        )
        for n_s, name in matches:
            n = int(n_s)
            if 1 <= n <= cap:
                name = re.sub(r"\s+Page\s*:\s*\d+(?:\s*(?:of|/)\s*\d+)?$", "", name, flags=re.I)
                rows.setdefault(n, re.sub(r"\s+", " ", name).strip())
    return rows


def parse_flat(text, announced=None):
    cleaned = re.sub(r"(?im)^(Roll of Successful.*|.*?\bLICENSURE\s+EXAMINATION\b.*|Held on\b.*|Released on\b.*|Seq\.?\s*No\.?\b.*)$", " ", text)
    cleaned = re.sub(r"(?im)\bpage\s*:\s*\d+(?:\s*(?:of|/)\s*\d+)?", " ", cleaned)
    flat = re.sub(r"\s+", " ", cleaned)
    cap = int(announced * 1.1) + 1 if announced else 10**6
    rows = {}
    for n, name in re.findall(r"(?:^|\s)(\d{1,6})\s+([^\W\d_][^\d]*?)(?=\s+\d{1,6}\s+[^\W\d_]|\s*$)", flat):
        if 1 <= int(n) <= cap:
            rows.setdefault(int(n), name.strip())
    return rows


def complete(rows, passed):
    n = passed or max(rows, default=0)
    return n > 0 and all(i in rows for i in range(1, n + 1))


def published_on_text(raw):
    """Turns any PRC date text into 'November 10, 2026'. Returns '' if it can't."""
    from datetime import datetime
    raw = str(raw or "").strip()
    try:
        iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if iso:
            d = datetime(int(iso[1]), int(iso[2]), int(iso[3]))
            return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")
    except ValueError:
        return ""
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*[-–]\s*\d{1,2})?,?\s+(\d{4})", raw)
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                d = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", fmt)
                return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")
            except ValueError:
                continue
    return ""


def page_published_on(url, fallback=None):
    """PRC's publish date, taken from the Watcher's saved value only. GitHub does not contact PRC."""
    return published_on_text(fallback)
