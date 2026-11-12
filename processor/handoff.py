"""Blueprint handoff: builds the exact five-field `successful_list.found` message.

Pure functions only (no network, no GitHub, no Telegram). prepare.py calls these before
it starts a run, so a wrong or guessed link is never processed or published.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit

EVENT = "successful_list.found"
PRC_HOSTS = {"www.prc.gov.ph", "prc.gov.ph"}
# Blueprint: the list must be a direct Google Drive file link or a PRC-hosted PDF, never a guessed or search URL.
DRIVE_FILE = re.compile(r"^https://drive\.google\.com/file/d/[A-Za-z0-9_-]{10,200}/view(?:\?[^#\s]*)?$")
PRC_PDF = re.compile(r"^https://(?:www\.)?prc\.gov\.ph/[^\s#?]+\.pdf(?:\?[^\s#]*)?$", re.I)
# Wanted label: "List of Successful Examinees", with reasonable wording variations.
WANTED = re.compile(r"(?:list|roll)\s+of\s+successful|successful\s+examinees|list\s+of\s+passers", re.I)
# Never send these, even if the label also contains the word "list".
UNWANTED = re.compile(r"top\s*-?\s*10|top\s*-?\s*notch|performance\s+of\s+(?:the\s+)?schools?|school\s+performance|full\s+text|official\s+result", re.I)


class HandoffError(ValueError):
    """Raised when a required field is missing or a link fails the blueprint checks."""


def _text(name, value):
    text = " ".join(str(value or "").split())
    if not text:
        raise HandoffError(f"{name} is required.")
    return text


def _prc_announcement_url(value):
    parts = urlsplit(_text("prc_announcement_url", value))
    if parts.scheme != "https" or (parts.hostname or "").lower() not in PRC_HOSTS or parts.username or parts.password:
        raise HandoffError("prc_announcement_url must be an HTTPS prc.gov.ph address.")
    return parts.geturl()


def _is_allowed_list_link(href):
    return bool(DRIVE_FILE.match(href) or PRC_PDF.match(href))


def _successful_examinees_url(value):
    text = _text("successful_examinees_url", value)
    if not _is_allowed_list_link(text):
        raise HandoffError("successful_examinees_url must be a Google Drive file link (/file/d/{id}/view) "
                           "or a prc.gov.ph PDF.")
    return text


def build_successful_list_event(profession, examination, prc_announcement_url, successful_examinees_url):
    """Returns exactly the five fields Prepare reads, in fixed order. Raises HandoffError otherwise."""
    return {
        "event": EVENT,
        "profession": _text("profession", profession),
        "examination": _text("examination", examination),
        "prc_announcement_url": _prc_announcement_url(prc_announcement_url),
        "successful_examinees_url": _successful_examinees_url(successful_examinees_url),
    }


def select_list_link(links):
    """links: iterable of (label, href) from the official announcement page.

    Returns ("found", href) for exactly one wanted list link (Drive or prc.gov.ph PDF),
    ("awaiting", None) when none exists (wait and retry, never guess),
    or ("ambiguous", [hrefs]) when several different wanted links exist (hold for review).
    """
    wanted = []
    for label, href in links:
        label = " ".join((label or "").split())
        href = (href or "").strip()
        if not WANTED.search(label) or UNWANTED.search(label):
            continue
        if not _is_allowed_list_link(href) or href in wanted:
            continue
        wanted.append(href)
    if not wanted:
        return "awaiting", None
    if len(wanted) == 1:
        return "found", wanted[0]
    return "ambiguous", wanted


def handoff_key(event):
    """Stable dedupe key. A corrected list (new Drive link) gives a new key, so an update is sent."""
    canonical = json.dumps(
        [event["prc_announcement_url"], event["successful_examinees_url"]], separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_handoff(work_dir, *, profession, examination, announcement_url, list_url):
    """Records the handoff decision in handoff.json.

    Shadow mode by default: nothing is blocked. Set HANDOFF_ENFORCE=1 to make a blocked
    handoff stop the run (only after live lists are confirmed to pass the Drive check).
    """
    import os
    from pathlib import Path

    record = {"status": "ready", "event": None, "key": None, "error": None}
    try:
        event = build_successful_list_event(profession, examination, announcement_url, list_url)
        record["event"] = event
        record["key"] = handoff_key(event)
    except HandoffError as err:
        record["status"] = "blocked"
        record["error"] = str(err)
    (Path(work_dir) / "handoff.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    if record["status"] == "blocked" and os.environ.get("HANDOFF_ENFORCE") == "1":
        raise HandoffError(record["error"])
    return record
