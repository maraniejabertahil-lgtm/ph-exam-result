import io, json, sys, time
from common import *


def try_download(link):
    fid = drive_id(link)
    urls = ([f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
             f"https://drive.google.com/uc?export=download&id={fid}"] if fid else [link])
    for u in urls:
        try:
            b = requests.get(u, headers=HDR, timeout=60).content
            if b[:5] == b"%PDF-":
                return b
        except Exception as e:
            print("download error", e)
    print("Drive blocked the direct download")
    return None


def pdf_rows(raw, passed):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    rows = parse_rows(text, passed)
    return rows if complete(rows, passed) else parse_flat(text, passed)


def main():
    url = os.environ["URL"]
    detected = int(os.environ.get("DETECTED_AT") or now_ms())
    title, passed, total, link = article(url)
    m = TITLE.match(title)
    if not m:
        print("not an exam article:", title); out(mode="skip"); return
    month, year, exam = m["m"].title(), int(m["y"]), m["exam"].strip()
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
    mode = "screens"
    raw = try_download(link)
    if raw:
        rows = pdf_rows(raw, passed)
        if complete(rows, passed):
            (WORK / "exact.json").write_text(json.dumps([{str(k): v for k, v in rows.items()}]))
            mode = "exact"
    (WORK / "job.json").write_text(json.dumps(job))
    out(mode=mode, link=link, passed=passed or 0)


if __name__ == "__main__":
    main()
