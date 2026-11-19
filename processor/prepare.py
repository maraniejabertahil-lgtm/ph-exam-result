import json, os, re, subprocess, sys, time
from common import *
from lists import parse_title, result_lists, SUCCESS_LINK, _label
from handoff import write_handoff


def lists_from_info(info):
    """Build the list records from the details the Cloudflare Watcher saved, so GitHub does not contact PRC."""
    links = [L for L in info.get("links") or [] if SUCCESS_LINK.search(L.get("text", ""))]
    counts = [(c["passed"], c["total"], c.get("ctx", ""), "passed" in c.get("after", ""))
              for c in info.get("counts") or []]
    lists, seen = [], set()
    for L in links:
        href = L["href"]
        if href in seen:
            continue
        seen.add(href)
        label = _label(L.get("text", ""))
        if len(links) == 1:
            pick = next((c for c in counts if c[3]), counts[0] if counts else None)
        else:
            pick = next((c for c in counts if label and re.search(rf"\b{re.escape(label)}\b", c[2], re.I)), None)
        lists.append(dict(label=label, link=href, passed=pick[0] if pick else None, total=pick[1] if pick else None))
    return lists


def main():
    url = os.environ["URL"]
    detected = int(os.environ.get("DETECTED_AT") or now_ms())
    want = (os.environ.get("LIST") or "").strip()
    kind = (os.environ.get("KIND") or "").strip()
    try:
        info = json.loads(os.environ.get("INFO") or "null") or {}
    except ValueError:
        info = {}
    if kind == "announcement":
        title = info.get("title") or url.rsplit("/", 1)[-1]
        parsed = parse_title(title)
        month, year, exam = (parsed[0], parsed[1], parsed[2]) if parsed else ("", 0, title)
        month = " ".join(w if w.lower() in ("and", "&") else w.title() for w in month.split())
        job = dict(url=url, title=title, month=month, year=year, exam=exam, kind="schedule",
                   slug=slug(f"{month}-{year}-{exam}") if parsed else slug(url.rsplit("/", 1)[-1]),
                   link=None, passed=None, total=None, list="", info=info)
        (WORK / "job.json").write_text(json.dumps(job)); out(mode="state"); return

    from_info = bool(info.get("title")) and "links" in info and "counts" in info
    if from_info:
        title, lists = info["title"], lists_from_info(info)
        print(f"using the Watcher's saved details: {len(lists)} list link(s); PRC not contacted")
    else:
        title, lists = result_lists(url)

    parsed = parse_title(title)
    if not parsed:
        print("not an exam article:", title); out(mode="skip"); return
    month_raw, year, exam = parsed
    month = " ".join(w if w.lower() in ("and", "&") else w.title() for w in month_raw.split())
    base = dict(url=url, title=title, month=month, year=year, detected=detected, info=info,
                published_on=page_published_on(url, info.get("published_at")))
    low = title.lower()
    if "result" not in low:
        job = dict(base, exam=exam, kind="schedule", slug=slug(f"{month}-{year}-{exam}"), link=None, passed=None, total=None, list="")
        (WORK / "job.json").write_text(json.dumps(job))
        out(mode="state" if ("schedule" in low or "room assignment" in low) else "skip"); return

    deadline = time.time() + 20 * 60
    while not lists and not from_info and time.time() < deadline:
        time.sleep(5); title, lists = result_lists(url)
    if not lists:
        tg(f"⚠️ {title}: official list link not found after 20 min"); out(mode="skip"); sys.exit(1)
    if len(lists) > 1 and not want:
        ref = os.environ.get("GITHUB_REF_NAME", "main")
        info_str = json.dumps(info)
        for i in range(len(lists)):
            subprocess.run(["gh", "workflow", "run", "process.yml", "--ref", ref,
                            "-f", f"url={url}", "-f", f"list={i}",
                            "-f", "attempt=1", "-f", f"detected={detected}",
                            "-f", f"info={info_str}"], check=True)
        names = ", ".join(L["label"] or "all" for L in lists)
        tg(f"📋 {title}\n{len(lists)} result lists found: {names}. Each one is processed separately.")
        out(mode="fanout"); return
    idx = int(want or 0)
    if idx >= len(lists):
        tg(f"⚠️ {title}: list {idx} not found"); out(mode="skip"); sys.exit(1)
    L = lists[idx]
    label = L["label"]
    job = dict(base,
               title=f"{title} ({label})" if label else title,
               exam=f"{exam} ({label})" if label else exam,
               kind="result",
               slug=slug(f"{month}-{year}-{exam}" + (f"-{label}" if label else "")),
               link=L["link"], passed=L["passed"], total=L["total"],
               list=str(idx) if len(lists) > 1 else "")
    (WORK / "job.json").write_text(json.dumps(job))
    write_handoff(WORK, profession=exam, examination=title, announcement_url=url, list_url=L["link"])
    out(mode="screens", link=L["link"], passed=L["passed"] or 0)


if __name__ == "__main__":
    main()
