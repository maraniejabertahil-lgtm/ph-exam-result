import json, os, subprocess, sys, time
from common import *
from lists import parse_title, result_lists


def main():
    url = os.environ["URL"]
    detected = int(os.environ.get("DETECTED_AT") or now_ms())
    want = (os.environ.get("LIST") or "").strip()      # set only on the per-list runs
    title, lists = result_lists(url)
    parsed = parse_title(title)
    if not parsed:
        print("not an exam article:", title); out(mode="skip"); return
    month_raw, year, exam = parsed
    month = " ".join(w if w.lower() in ("and", "&") else w.title() for w in month_raw.split())
    base = dict(url=url, title=title, month=month, year=year, detected=detected)
    low = title.lower()
    if "result" not in low:
        job = dict(base, exam=exam, kind="schedule", slug=slug(f"{month}-{year}-{exam}"), link=None, passed=None, total=None, list="")
        (WORK / "job.json").write_text(json.dumps(job))
        out(mode="state" if ("schedule" in low or "room assignment" in low) else "skip"); return
    deadline = time.time() + 20 * 60
    while not lists and time.time() < deadline:
        time.sleep(5); title, lists = result_lists(url)
    if not lists:
        tg(f"⚠️ {title}: official list link not found after 20 min"); out(mode="skip"); sys.exit(1)
    if len(lists) > 1 and not want:
        # one article, several lists: start one full run per list, each with its own slug and shards
        for i in range(len(lists)):
            subprocess.run(["gh", "workflow", "run", "process.yml", "-f", f"url={url}", "-f", f"list={i}",
                            "-f", "attempt=1", "-f", f"detected={detected}"], check=True)
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
    # Screenshot-only: never download or read the PDF text. Always screenshot the public preview and read it with OCR.
    out(mode="screens", link=L["link"], passed=L["passed"] or 0)


if __name__ == "__main__":
    main()
