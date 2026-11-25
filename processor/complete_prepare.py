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
    "schools": re.compile(r"performance\s+of\s+schools|schools?\s+performance", re.I),
    "topnotchers": re.compile(r"top\s*10|highest\s+places?|topnotchers?", re.I),
    "names": re.compile(r"(?:list|roll)\s+of\s+(?:successful|passers)|successful\s+examinees", re.I),
}


def read_alert():
    if not ALERT_JOB.exists():
        return None
    return json.loads(ALERT_JOB.read_text())


def links_from_info(info, list_label=""):
    """Sort the links the Cloudflare Watcher saved into the three kinds."""
    found = {k: [] for k in KINDS}
    all_links = info.get("links") or []
    for a in all_links:
        did = drive_id(a.get("href", ""))
        if not did:
            continue
        k = a.get("kind")
        if k in found:
            kinds = [k]
        elif k is None:
            kinds = [kind for kind, rx in KINDS.items() if rx.search(a.get("text", ""))]
        else:
            kinds = []
        label = (a.get("label") or "").strip()
        for kind in kinds:
            if kind in ("schools", "topnotchers") and list_label and label and label.casefold() != list_label.casefold():
                continue
            if not any(x["id"] == did for x in found[kind]):
                found[kind].append({"id": did, "label": label})
    return found


def set_output(**values):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def update_links(article, schools_raw, top_raw, schools_many="", top_many=""):
    """Late links: collect all schools and top-10 links sent by the Worker or manual inputs."""
    links = {"schools": [], "topnotchers": [], "names": []}
    details = {"schools": [], "topnotchers": []}
    for key, raw, many in (("schools", schools_raw, schools_many), ("topnotchers", top_raw, top_many)):
        values = []
        if many:
            try:
                values.extend(json.loads(many))
            except (TypeError, ValueError):
                print(f"WARNING: invalid {key.upper()}_LINKS JSON")
        if raw:
            values.append({"href": raw, "label": ""})
        for value in values:
            if isinstance(value, str):
                value = {"href": value}
            did = drive_id(value.get("href", ""))
            if did:
                if did not in links[key]:
                    links[key].append(did)
                    details[key].append({"id": did, "label": (value.get("label") or "").strip()})
            else:
                print(f"WARNING: could not read a Google Drive ID from the {key} link: {value}")
    print({k: len(v) for k, v in links.items()})
    if not article or not (links["schools"] or links["topnotchers"]):
        print("nothing to add: no article address, or no usable schools / top-10 link")
        set_output(mode="skip")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "links.json").write_text(json.dumps({
        "article": article, "target_slug": "", "list_label": "", "expected_lists": None,
        "links": links, "link_details": details,
    }))
    print(f"late links for {article}")
    set_output(mode="screens", article=article)


def main():
    manual_article = (os.environ.get("ARTICLE_URL") or "").strip()
    manual_schools = (os.environ.get("SCHOOLS_URL") or "").strip()
    manual_top = (os.environ.get("TOPNOTCHERS_URL") or "").strip()
    manual_schools_many = os.environ.get("SCHOOLS_LINKS") or ""
    manual_top_many = os.environ.get("TOPNOTCHERS_LINKS") or ""
    manual_names = (os.environ.get("NAMES_URL") or "").strip()

    if os.environ.get("UPDATE_ONLY") == "1":
        update_links(manual_article, manual_schools, manual_top, manual_schools_many, manual_top_many)
        return

    job = read_alert()
    if not job and not manual_article:
        print("no alert file from the first pipeline for this run: skipped")
        set_output(mode="skip")
        return
    if job and job.get("dry_run") and not manual_article:
        print("Pipeline 1 dry run: skipping Pipeline 2")
        set_output(mode="skip")
        return
    if job and job.get("kind") != "result" and not manual_article:
        print(f"not a results article (kind={job.get('kind')}): skipped")
        set_output(mode="skip")
        return

    url = manual_article or job["url"]
    info = (job or {}).get("info") or {}
    list_label = "" if manual_article else ((job or {}).get("list_label") or "")
    target_slug = "" if manual_article else ((job or {}).get("slug") or "")
    source_note = "manual inputs" if manual_article else "the first pipeline's alert"
    print(f"article (from {source_note}): {url}")

    details = links_from_info(info, list_label)
    links = {k: [x["id"] for x in v] for k, v in details.items()}
    for key, raw in (("schools", manual_schools), ("topnotchers", manual_top), ("names", manual_names)):
        if raw:
            did = drive_id(raw)
            if did:
                links[key] = [did]
                details[key] = [{"id": did, "label": ""}]
            else:
                print(f"WARNING: could not parse Google Drive ID from {key}_url: {raw}")

    if not manual_names and job and job.get("link"):
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
    (WORK / "links.json").write_text(json.dumps({
        "article": url, "target_slug": target_slug, "list_label": list_label,
        "expected_lists": (job or {}).get("expected_lists") if not manual_article else None,
        "links": links, "link_details": details,
    }))
    set_output(mode="screens", article=url)


if __name__ == "__main__":
    main()
