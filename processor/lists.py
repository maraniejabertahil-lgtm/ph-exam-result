"""PRC results articles: read the title and every 'List of Successful Examinees' link for ANY exam."""
import re
from common import HDR, MONTHS

SUCCESS_LINK = re.compile(r"(?:list|roll)\s+of\s+successful", re.I)
# "18,376 elementary teachers out of 32,796 examinees" / "1,234 passed out of 2,000"
COUNT = re.compile(r"([\d,]+)\s+((?:[A-Za-z()'\-]+\s+){0,6}?)out of\s+([\d,]+)", re.I)
TITLE_HEAD = re.compile(rf"^(?P<m>(?:{MONTHS})(?:\s*(?:,|&|and)\s*(?:{MONTHS}))*)\s+(?P<y>20\d\d)\s+(?P<rest>.+)$", re.I)
# "Licensure Examination for Professional Teachers Results Released ..."
TITLE_FOR = re.compile(r"^(?:Computer[- ]Based\s+)?Licen[sc]ure\s+(?:Examination|Exam)\s+(?:for|of)\s+(?P<exam>.+?)"
                       r"(?:\s+(?:Results?|Examinations?|Released|Schedules?|Room|Passers?|Lists?)\b.*)?$", re.I)
# "Midwives Licensure Examination Results Released ..."
TITLE_BEFORE = re.compile(r"^(?P<exam>.+?)\s+(?:Computer[- ]Based\s+)?Licen[sc]ure\b", re.I)


def parse_title(title):
    """-> (month text, year, exam name) for any PRC exam title, or None if it is not an exam title."""
    h = TITLE_HEAD.match(title.strip())
    if not h:
        return None
    rest = h["rest"].strip()
    t = TITLE_FOR.match(rest) or TITLE_BEFORE.match(rest)
    if not t or not t["exam"].strip():
        return None
    return h["m"], int(h["y"]), t["exam"].strip()


def _label(text):
    """'List of Successful Examinees for Elementary' -> 'Elementary'; plain 'List of Successful Examinees' -> ''."""
    lab = re.sub(r"^.*?(?:list|roll)\s+of\s+successful\s*(?:examinees?|passers?|candidates?)?", "", text.strip(), flags=re.I)
    lab = re.sub(r"^\s*(?:for|of|in)\s+", "", lab.strip(" -:,"), flags=re.I)
    return lab.strip(" -:,")


def _counts(body):
    found = []
    for m in COUNT.finditer(body):
        tail = body[m.end(): m.end() + 30].lower()
        found.append((int(m[1].replace(",", "")), int(m[3].replace(",", "")), m[0], "passed" in tail))
    return found


def result_lists(url):
    """-> (page title, [{label, link, passed, total}, ...]) with one entry per result list on the page."""
    import requests
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(requests.get(url, headers=HDR, timeout=40).text, "html.parser")
    title = (soup.title.string or "").split("|")[0].strip()
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if SUCCESS_LINK.search(text) and a["href"] not in seen:
            seen.add(a["href"])
            links.append((_label(text), a["href"]))
    counts = _counts(body)
    lists = []
    for label, href in links:
        if len(links) == 1:
            pick = next((c for c in counts if c[3]), counts[0] if counts else None)
        else:
            pick = next((c for c in counts if label and re.search(rf"\b{re.escape(label)}\b", c[2], re.I)), None)
        lists.append(dict(label=label, link=href, passed=pick[0] if pick else None, total=pick[1] if pick else None))
    return title, lists
