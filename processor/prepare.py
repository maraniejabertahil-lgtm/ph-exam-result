import json, sys, time
from common import *


def main():
    url = os.environ["URL"]
    detected = int(os.environ.get("DETECTED_AT") or now_ms())
    title, passed, total, link = article(url)
    m = TITLE.match(title)
    if not m:
        print("not an exam article:", title); out(mode="skip"); return
    month = " ".join(w if w.lower() in ("and", "&") else w.title() for w in m["m"].split())
    year, exam = int(m["y"]), m["exam"].strip()
    job = dict(url=url, title=title, month=month, year=year, exam=exam, slug=slug(f"{month}-{year}-{exam}"),
               detected=detected, passed=passed, total=total, link=link)
    low = title.lower()
    if "result" not in low:
        job["kind"] = "schedule"
        (WORK / "job.json").write_text(json.dumps(job))
        out(mode="state" if ("schedule" in low or "room assignment" in low) else "skip"); return
    job["kind"] = "result"
    deadline = time.time() + 20 * 60
    while not link and time.time() < deadline:
        time.sleep(5); title, passed, total, link = article(url)
    if not link:
        tg(f"⚠️ {title}: official list link not found after 20 min"); out(mode="skip"); sys.exit(1)
    job.update(link=link, passed=passed, total=total)
    # Screenshot-only: never download or read the PDF text. Always screenshot the public preview and read it with OCR.
    (WORK / "job.json").write_text(json.dumps(job))
    out(mode="screens", link=link, passed=passed or 0)


if __name__ == "__main__":
    main()
