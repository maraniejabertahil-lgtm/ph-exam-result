"""Second pipeline, stage 1. Works on the same article as the first pipeline.

GitHub never contacts the PRC website, because PRC refuses connections from GitHub's servers.
The article address and the official list links (Google Drive) come from the Cloudflare Watcher,
through the first pipeline's alert file (job.json). If those links are missing, this stage stops
with a clear message instead of trying PRC."""
import json, os, re, sys
from pathlib import Path

from common import drive_id

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


def links_from_info(info):
    """Sort the links the Cloudflare Watcher saved into the three kinds."""
    found = {k: [] for k in KINDS}
    for a in info.get("links") or []:
        did = drive_id(a.get("href", ""))
        if not did:
            continue
        for kind, rx in KINDS.items():
            if rx.search(a.get("text", "")) and did not in found[kind]:
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
    info = job.get("info") or {}
    print(f"article (from the first pipeline's alert): {url}")

    links = links_from_info(info)
    print({k: len(v) for k, v in links.items()})

    if not links["names"]:
        print("STOP: the Cloudflare Watcher did not save an official list link for this article.")
        print("GitHub does not contact PRC, so this stage cannot continue without that link.")
        sys.exit(1)

    if not links["schools"] or not links["topnotchers"]:
        print("WARNING: the schools or top-notchers link is missing; those pages will be skipped.")

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "links.json").write_text(json.dumps({"article": url, "links": links}))
    set_output(mode="screens", article=url)


if __name__ == "__main__":
    main()
