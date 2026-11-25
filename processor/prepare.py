import io, json, os, re, subprocess, sys, time
from common import *
from lists import parse_title, SUCCESS_LINK, _label
from handoff import write_handoff


def lists_from_info(info):
    """Build the list records from the details the Cloudflare Watcher saved, so GitHub does not contact PRC.
    Uses the Watcher's "kind" field first, falls back to text rules, then unlabeled Google Drive links."""
    all_links = info.get("links") or []
    links = [L for L in all_links if L.get("kind") == "names"]
    if not links:
        links = [L for L in all_links if SUCCESS_LINK.search(L.get("text", ""))]
    if not links:
        links = [
            L for L in all_links
            if not L.get("kind")
            and drive_id(L.get("href", ""))
            and not re.search(r"full\s+text|performance\s+of\s+schools|schools?\s+performance|top\s*10|highest\s+places?|topnotchers?|privacy|oath|registration|form", L.get("text", ""), re.I)
        ]
    counts = []
    for c in info.get("counts") or []:
        p, t = c.get("passed"), c.get("total")
        if t is not None and p is not None and p > t:
            continue
        before_local = re.split(r"[.;!?]|\d{2,}", str(c.get("before") or ""))[-1]
        after_raw = str(c.get("after") or "")
        after_local = re.split(r"[.;!?]|\band\s+[\d,]+|\d{2,}", after_raw, flags=re.I)[0]
        counts.append((p, t, str(c.get("ctx") or ""), f"{before_local} {c.get('ctx') or ''} {after_local}", "passed" in after_raw.lower()))
    lists, seen = [], set()
    for L in links:
        href = L["href"]
        if href in seen:
            continue
        seen.add(href)
        label = L["label"] if L.get("label") is not None else _label(L.get("text", ""))
        if len(links) == 1:
            pick = next((c for c in counts if c[4]), counts[0] if counts else None)
        else:
            rx = re.compile(rf"\b{re.escape(label)}\b", re.I) if label else None
            pick = (next((c for c in counts if rx and rx.search(c[2])), None)
                    or next((c for c in counts if rx and rx.search(c[3])), None))
        lists.append(dict(label=label, link=href, passed=pick[0] if pick else None, total=pick[1] if pick else None))
    return lists


def _opt_int(val):
    val = (val or "").strip().replace(",", "")
    return int(val) if val.isdigit() else None


def try_extract_exact(link, passed):
    """Fast path: download Drive PDF if allowed and extract selectable text directly.
    Returns (rows_or_None, pdf_bytes_or_None, has_nothing_follows)."""
    t0 = time.time()
    pdf_bytes = download_drive_pdf(link, timeout=55)
    if not pdf_bytes:
        print("direct PDF download unavailable; using preview")
        return None, None, False
    print(f"downloaded PDF ({len(pdf_bytes) // 1024} KB) in {time.time() - t0:.1f}s")
    rows, has_eof = {}, False
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
        has_eof = bool(re.search(r"NOTHING\s+FOLLOWS", full_text, re.I))
        if len(full_text.strip()) < 100:
            print("PDF has no selectable text (scanned PDF); using image OCR")
            return None, pdf_bytes, has_eof
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
            has_eof = has_eof or bool(re.search(r"NOTHING\s+FOLLOWS", full_text, re.I))
            rows2 = parse_pdf_text(full_text, passed)
            if len(rows2) > len(rows):
                rows = rows2
        except Exception as e:
            print("pdfplumber fallback error:", e)
    print(f"PDF text extraction got {len(rows)}/{passed or '?'} rows in {time.time() - t0:.1f}s")
    if passed and not complete(rows, passed):
        missing = [i for i in range(1, passed + 1) if i not in rows]
        print(f"missing rows ({len(missing)}): {missing[:20]}")
    return (rows if complete(rows, passed) else None), pdf_bytes, has_eof


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

    if kind == "notice":
        title = info.get("title") or url.rstrip("/").rsplit("/", 1)[-1]
        waited = info.get("waited_hours") or 3
        tg(f"⏳ {title}: PRC posted this result article {waited} hours ago, but no official list link is attached yet. Watching slowly for 3 more hours.\n{url}")
        out(mode="skip"); return

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
               list=str(idx) if len(lists) > 1 else "",
               dry_run=os.environ.get("DRY_RUN") == "true",
               list_label=label, expected_lists=len(lists))
    write_handoff(WORK, profession=exam, examination=title, announcement_url=url, list_url=L["link"])

    exact_rows, pdf_bytes, has_eof = try_extract_exact(L["link"], L["passed"])
    job["has_nothing_follows"] = has_eof
    (WORK / "job.json").write_text(json.dumps(job))
    if exact_rows:
        (WORK / "exact.json").write_text(json.dumps([{str(k): v for k, v in sorted(exact_rows.items())}]))
        out(mode="exact", link=L["link"], passed=L["passed"] or len(exact_rows))
        return
    if pdf_bytes and len(pdf_bytes) <= 150 * 1024 * 1024:
        (WORK / "source.pdf").write_bytes(pdf_bytes)
    elif not drive_id(L["link"]):
        msg = f"⚠️ {job['title']}: list link is neither directly downloadable nor a Google Drive file ({L['link']})."
        print(msg); tg(msg); out(mode="skip"); sys.exit(1)
    out(mode="screens", link=L["link"], passed=L["passed"] or 0)


if __name__ == "__main__":
    main()
