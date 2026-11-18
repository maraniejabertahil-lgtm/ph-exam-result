"""Second pipeline, stage 1. Works on the same article as the first pipeline.

The article address is taken from the first pipeline's own alert file (job.json) for the
run that just finished. The page is read the same way as prepare.py reads it: one request
per try, and if the names link is not there yet, wait 5 seconds and try again, for up to
20 minutes. A refused connection stops the stage at once, as in the first pipeline."""
import json, os, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from common import HDR, drive_id

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
ALERT_JOB = HERE / "alert" / "job.json"

KINDS = {
    "schools": re.compile(r"performance\s+of\s+schools", re.I),
    "topnotchers": re.compile(r"top\s*10|highest\s+places", re.I),
    "names": re.compile(r"(?:list|roll)\s+of\s+successful", re.I),
}


def read_alert():
    if not ALERT_JOB.exists():
        return None
    return json.loads(ALERT_JOB.read_text())


def fetch_links(url):
    # Same request as lists.py. No try/except: a refusal raises at once, as in the first pipeline.
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
    return found


def set_output(**values):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def main():
    job = read_alert()
    if not job:
        print("no alert file from the first pipeline for this run: skipped")
        set_output(mode="skip")
        return
    if job.get("kind") != "result":
        print(f"not a results article (kind={job.get('kind')}): skipped")
        set_output(mode="skip")
        return

    url = job["url"]
    print(f"article (from the first pipeline's alert): {url}")

    links = fetch_links(url)
    deadline = time.time() + 20 * 60
    while not links["names"] and time.time() < deadline:
        print("names link not there yet, waiting 5s")
        time.sleep(5)
        links = fetch_links(url)
    if not links["names"]:
        print("gave up after 20 minutes: no names link found")
        sys.exit(1)

    print({k: len(v) for k, v in links.items()})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "links.json").write_text(json.dumps({"article": url, "links": links}))
    set_output(mode="screens", article=url)


if __name__ == "__main__":
    main()
