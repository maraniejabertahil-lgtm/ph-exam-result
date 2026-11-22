"""Second pipeline, stage 1. Works on the same article as the first pipeline.
GitHub never contacts the PRC website, because PRC refuses connections from GitHub's servers.
The article address and the official list links (Google Drive) come from the Cloudflare Watcher,
through the first pipeline's alert file (job.json), or from manual workflow inputs.

Which link is which (names / schools / topnotchers) is decided by the Watcher (its LINK_KEYWORDS), which
puts a "kind" on every link. Older alerts without a "kind" still work through the text rules in KINDS below.

UPDATE_ONLY=1 is used by the add-links workflow ("late links"): PRC attached the schools and/or top 10 link
after the list, so only those pages are needed and the names list is not read again."""

import json, os, re, sys
from pathlib import Path
from common import drive_id

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
ALERT_JOB = HERE / "alert" / "job.json"

# Fallback only (alerts that carry no "kind"). The real keywords live in the Cloudflare Worker.
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
    all_links = info.get("links") or []
    uses_kind = any("kind" in a for a in all_links)
    for a in all_links:
        did = drive_id(a.get("href", ""))
        if not did:
            continue
        if uses_kind:
            kinds = [a["kind"]] if a.get("kind") in found else []
        else:
            kinds = [k for k, rx in KINDS.items() if rx.search(a.get("text", ""))]
        for kind in kinds:
            if did not in found[kind]:
                found[kind].append(did)
    return found


def set_output(**values):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def update_links(article, schools_raw, top_raw):
    """Late links: only the schools and top-10 links are needed."""
    links = {"schools": [], "topnotchers": [], "names": []}
    for key, raw in (("schools", schools_raw), ("topnotchers", top_raw)):
        if raw:
            did = drive_id(raw)
            if did:
                links[key] = [did]
            else:
                print(f"WARNING: could not read a Google Drive ID from the {key} link: {raw}")
    print({k: len(v) for k, v in links.items()})
    if not article or not (links["schools"] or links["topnotchers"]):
        print("nothing to add: no article address, or no usable schools / top-10 link")
        set_output(mode="skip")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "links.json").write_text(json.dumps({"article": article, "links": links}))
    print(f"late links for {article}")
    set_output(mode="screens", article=article)


def main():
    manual_article = (os.environ.get("ARTICLE_URL") or "").strip()
    manual_schools = (os.environ.get("SCHOOLS_URL") or "").strip()
    manual_top = (os.environ.get("TOPNOTCHERS_URL") or "").strip()
    manual_names = (os.environ.get("NAMES_URL") or "").strip()

    if os.environ.get("UPDATE_ONLY") == "1":
        update_links(manual_article, manual_schools, manual_top)
        return

    job = read_alert()
    if not job and not manual_article:
        print("no alert file from the first pipeline for this run: skipped")
        set_output(mode="skip")
        return
    if job and job.get("kind") != "result" and not manual_article:
        print(f"not a results article (kind={job.get('kind')}): skipped")
        set_output(mode="skip")
        return

    url = manual_article or job["url"]
    info = (job or {}).get("info") or {}
    source_note = "manual inputs" if manual_article else "the first pipeline's alert"
    print(f"article (from {source_note}): {url}")

    links = links_from_info(info)
    for key, raw in (("schools", manual_schools), ("topnotchers", manual_top), ("names", manual_names)):
        if raw:
            did = drive_id(raw)
            if did:
                links[key] = [did]
            else:
                print(f"WARNING: could not parse Google Drive ID from {key}_url: {raw}")

    if not links["names"] and job and job.get("link"):
        did = drive_id(job["link"])
        if did:
            links["names"] = [did]

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
