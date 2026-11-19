"""Read PRC results articles and find every list of successful examinees."""

import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import HDR, MONTHS


SUCCESS_LINK = re.compile(r"(?:list|roll)\s+of\s+successful", re.I)

COUNT = re.compile(
    r"([\d,]+)\s+((?:[A-Za-z()'\-]+\s+){0,6}?)out of\s+([\d,]+)",
    re.I,
)

TITLE_HEAD = re.compile(
    rf"^(?P<m>(?:{MONTHS})(?:\s*(?:,|&|and)\s*(?:{MONTHS}))*)"
    r"\s+(?P<y>20\d\d)\s+(?P<rest>.+)$",
    re.I,
)

TITLE_FOR = re.compile(
    r"^(?:Computer[- ]Based\s+)?(?:Licen[sc]ure\s+)?"
    r"(?:Examination|Exam)\s+(?:for|of)\s+(?P<exam>.+?)"
    r"(?:\s+(?:Results?|Examinations?|Released|Schedules?|Room|Passers?|Lists?)\b.*)?$",
    re.I,
)

TITLE_BEFORE = re.compile(
    r"^(?P<exam>.+?)\s+(?:Computer[- ]Based\s+)?(?:Licen[sc]ure|Examination)\b",
    re.I,
)

def get_page(url, tries=5):
    """Download a PRC article, retrying transient network and server errors."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid article URL: {url}")
    if tries < 1:
        raise ValueError("tries must be at least 1")

    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
    retryable_errors = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )

    session = requests.Session()
    session.headers.update(HDR)
    last_error = None

    try:
        for attempt in range(1, tries + 1):
            try:
                response = session.get(url, timeout=(15, 40), allow_redirects=True)

                if response.status_code in retryable_statuses:
                    raise requests.HTTPError(
                        f"Temporary HTTP {response.status_code}",
                        response=response,
                    )

                response.raise_for_status()

                if not response.content or not response.text.strip():
                    raise requests.ConnectionError("PRC returned an empty response.")

                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not any(
                    kind in content_type
                    for kind in ("text/html", "application/xhtml+xml")
                ):
                    raise ValueError(
                        f"Expected HTML, received Content-Type: {content_type}"
                    )

                return response.text

            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status not in retryable_statuses:
                    raise RuntimeError(
                        f"PRC returned HTTP {status}; request will not be retried."
                    ) from exc
                last_error = exc

            except retryable_errors as exc:
                last_error = exc

            if attempt < tries:
                delay = 10 * (2 ** (attempt - 1))
                print(
                    f"PRC fetch failed ({attempt}/{tries}): "
                    f"{type(last_error).__name__}: {last_error}. "
                    f"Retrying in {delay}s.",
                    flush=True,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"Could not download PRC article after {tries} attempts. "
            f"Last error: {last_error}"
        ) from last_error
    finally:
        session.close()


def parse_title(title):
    """Return (month text, year, exam name), or None for a non-exam title."""
    match = TITLE_HEAD.match(title.strip())
    if not match:
        return None

    rest = match["rest"].strip()
    exam_match = TITLE_FOR.match(rest) or TITLE_BEFORE.match(rest)
    if not exam_match or not exam_match["exam"].strip():
        return None

    return match["m"], int(match["y"]), exam_match["exam"].strip()


def _label(text):
    """Extract a list label from its link text."""
    label = re.sub(
        r"^.*?(?:list|roll)\s+of\s+successful\s*"
        r"(?:examinees?|passers?|candidates?)?",
        "",
        text.strip(),
        flags=re.I,
    )
    label = re.sub(
        r"^\s*(?:for|of|in)\s+",
        "",
        label.strip(" -:,"),
        flags=re.I,
    )
    return label.strip(" -:,")


def _counts(body):
    """Extract passed/total counts from article text."""
    found = []
    for match in COUNT.finditer(body):
        tail = body[match.end():match.end() + 30].lower()
        found.append((
            int(match[1].replace(",", "")),
            int(match[3].replace(",", "")),
            match[0],
            "passed" in tail,
        ))
    return found


def result_lists(url):
    """Return the article title and its successful-examinee list links."""
    soup = BeautifulSoup(get_page(url), "html.parser")

    title_tag = soup.title
    title = (
        title_tag.get_text(" ", strip=True).split("|")[0].strip()
        if title_tag
        else ""
    )
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        if not SUCCESS_LINK.search(text):
            continue

        href = urljoin(url, anchor["href"])
        if href in seen:
            continue

        seen.add(href)
        links.append((_label(text), href))

    counts = _counts(body)
    lists = []

    for label, href in links:
        if len(links) == 1:
            selected = next(
                (count for count in counts if count[3]),
                counts[0] if counts else None,
            )
        else:
            selected = next(
                (
                    count for count in counts
                    if label and re.search(
                        rf"\b{re.escape(label)}\b", count[2], re.I
                    )
                ),
                None,
            )

        lists.append({
            "label": label,
            "link": href,
            "passed": selected[0] if selected else None,
            "total": selected[1] if selected else None,
        })

    return title, lists
