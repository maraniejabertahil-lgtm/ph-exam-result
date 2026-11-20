import io, json, os, re, subprocess, sys, time
from common import *
from lists import parse_title, SUCCESS_LINK, _label
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


def _opt_int(val):
    val = (val or "").strip().replace(",", "")
    return int(val) if val.isdigit() else None


def try_extract_exact(link, passed):
    """Fast path: download Drive PDF if allowed and extract selectable text directly."""
    t0 = time.time()
    pdf_bytes = download_drive_pdf(link, timeout=55)
    if not pdf_bytes:
        print("direct PDF download unavailable; using preview")
        return None
    print(f"downloaded PDF ({len(pdf_bytes) // 1024} KB) in {time.time() - t0:.1f}s")
    rows = {}
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        pages_text = []
        for page in doc:
            tp = page.get_textpage()
            try:
                txt = tp.get_text_bounded() if hasattr(tp, "get_text_bounded") else tp.get_text_range()
            finally:
                tp.close()
                page.close()
            if txt:
                pages_text.append(txt)
        doc.close()
        full_text = "\n".join(pages_text)
        if len(full_text.strip()) < 100:
            print("PDF has no selectable text (scanned PDF); using image OCR")
            return None
        rows = parse_pdf_text(full_text, passed)
        if not complete(rows, passed):
            alt = parse_flat(re.split(r"NOTHING\s+FOLLOWS", full_text, maxsplit=1, flags=re.I)[0], passed)
            if len(alt) > len(rows):
                rows = alt
    except Exception as e:
        print("pypdfium2 text extraction error:", e)
    if not complete(rows, passed):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages_text = [p.extract_text(layout=True) or "" for p in pdf.pages]
            full_text = "\n".join(pages_text)
            rows2 = parse_pdf_text(full_text, passed)
            if len(rows2) > len(rows):
                rows = rows2
        except Exception as e:
            print("pdfplumber fallback error:", e)
    print(f"PDF text extraction got {len(rows)}/{passed or '?'} rows in {time.time() - t0:.1f}s")
    if passed and not complete(rows, passed):
    missing = [i for i in range(1, passed + 1) if i not in rows]
    print(f"missing rows ({len(missing)}): {missing[:20]}")
    if complete(rows, passed):
        return rows
    return None


def main():
    url = os.environ["URL"]
    detected = int(os.environ.get("DETECTED_AT") or now_ms())
    want = (os.environ.get("LIST") or "").strip()
    kind = (os.environ.get("KIND") or "").strip()
    manual_list_url = (os.environ.get("LIST_URL") or "").strip()

    try:
        info = json.loads(os.environ.get("INFO") or "null") or {}
    except ValueError:
        info = {}

    if kind == "announcement":
        title = info.get("title") or url.rsplit("/", 1)[-1]
        parsed = parse_title(title)
        month, year, exam = (parsed[0], parsed[1], parsed[2]) if parsed else ("", 0, title)
        month = " ".join(w if w.lower() in ("and", "&") else w.title() for w in month.split())
        job = dict(url=url, title=title, month=month, year=year, detected=detected, exam=exam, kind="schedule",
                   slug=slug(f"{month}-{year}-{exam}") if parsed else slug(url.rsplit("/", 1)[-1]),
                   link=None, passed=None, total=None, list="", info=info)
        (WORK / "job.json").write_text(json.dumps(job)); out(mode="state"); return

    from_info = bool(info.get("title")) and "links" in info and "counts" in info
    if from_info:
        title, lists = info["title"], lists_from_info(info)
        print(f"using the Watcher's saved details: {len(lists)} list link(s); PRC not contacted")
    elif manual_list_url:
        title = info.get("title") or url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        lists = [dict(
            label="",
            link=manual_list_url,
            passed=_opt_int(os.environ.get("TEST_PASSED")),
            total=_opt_int(os.environ.get("TEST_TOTAL")),
        )]
        print(f"using manual list_url; PRC not contacted ({title})")
    else:
        msg = f"⚠️ {url}: the Watcher saved no details and no list link was given. GitHub does not contact PRC, so processing stopped."
        print(msg)
        tg(msg)
        out(mode="skip")
        sys.exit(1)

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

    if not lists:
        msg = f"⚠️ {title}: no official list link in the Watcher's details. Processing stopped; GitHub does not contact PRC."
        print(msg)
        tg(msg)
        out(mode="skip")
        sys.exit(1)

    if len(lists) > 1 and not want:
        ref = os.environ.get("GITHUB_REF_NAME", "main")
        info_str = json.dumps(info)
        dry_run = os.environ.get("DRY_RUN") == "true"
        for i in range(len(lists)):
            cmd = ["gh", "workflow", "run", "process.yml", "--ref", ref,
                   "-f", f"url={url}", "-f", f"list={i}",
                   "-f", "attempt=1", "-f", f"detected={detected}",
                   "-f", f"info={info_str}"]
            if dry_run:
                cmd += ["-f", "dry_run=true"]
            subprocess.run(cmd, check=True)
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

    exact_rows = try_extract_exact(L["link"], L["passed"])
    if exact_rows:
        (WORK / "exact.json").write_text(json.dumps([{str(k): v for k, v in sorted(exact_rows.items())}]))
        out(mode="exact", link=L["link"], passed=L["passed"] or len(exact_rows))
        return
    out(mode="screens", link=L["link"], passed=L["passed"] or 0)


if __name__ == "__main__":
    main()
