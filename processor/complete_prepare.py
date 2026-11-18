"""Second pipeline, stage 1: finds the article and its three PDF links.
Follows the first pipeline's own wait pattern (prepare.py): if the links are not
there yet, or the connection is refused, wait 5 seconds and try again, for up to
20 minutes. This matches how the first pipeline waits for 'List of Successful
Examinees' to appear."""
import json, re, sys, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from common import HDR, drive_id

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WORK = Path(__file__).resolve().parent / "work"

KINDS = {
    "schools": re.compile(r"performance\s+of\s+schools", re.I),
    "topnotchers": re.compile(r"top\s*10|highest\s+places", re.I),
    "names": re.compile(r"list\s+of\s+successful", re.I),
}


def releases():
    out = []
    for p in DATA.glob("*.json"):
        if p.stem in ("state", "releases"):
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("meta"), dict):
            out.append((p, d))
    return out


def try_links(url):
    """One fetch attempt. Returns the links found, or None if the page loaded but none are there yet."""
    soup = BeautifulSoup(requests.get(url, headers=HDR, timeout=40).text, "html.parser")
    found = {k: [] for k in KINDS}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        did = drive_id(a["href"])
        if not did:
            continue
        for kind, rx in KINDS.items():
            if rx.search(text) and did not in found[kind]:
                found[kind].append(did)
    return found if any(found.values()) else None


def main():
    rel = releases()
    if not rel:
        print("no releases yet")
        sys.exit(1)
    latest = max(rel, key=lambda x: x[1]["meta"].get("built_at") or 0)[1]["meta"]
    article = latest.get("source")
    if not article:
        print("the newest release has no saved article address")
        sys.exit(1)
    print(f"article: {article}")

    deadline = time.time() + 20 * 60
    links = None
    while time.time() < deadline:
        try:
            links = try_links(article)
        except Exception as e:
            print(f"fetch failed, will retry: {str(e)[:200]}")
            links = None
        if links:
            break
        print("no PDF links on the page yet, waiting 5s")
        time.sleep(5)

    if not links:
        print("gave up after 20 minutes: no PDF links found")
        sys.exit(1)

    print({k: len(v) for k, v in links.items()})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "links.json").write_text(json.dumps({"article": article, "links": links}))
    out = __import__("os").environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"article={article}\n")


if __name__ == "__main__":
    main()
