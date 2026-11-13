"""Exam Results: the release list (/results/), a hub per release (/results/<slug>/),
and Topnotchers / Performance of Schools pages shown inside the site (not PDFs)."""
import html
from datetime import datetime

E = html.escape

CSS = """
.rlist{list-style:none;margin:8px 0 0;padding:0}
.rlist li{padding:18px 0;border-bottom:1px solid var(--line)}
.rdate{color:var(--mu);font-size:14px;margin:0 0 4px}
.rtitle{font-weight:600;color:var(--g2);text-decoration:none;line-height:1.35}
.rtitle:hover{text-decoration:underline}
.rex{margin:6px 0 0;font-size:15px;line-height:1.55}
.back{font-size:14px;margin:8px 0}
.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:18px 0 8px}
.links a,.links span{display:block;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--text);text-decoration:none;font-weight:600}
.links a:hover{border-color:var(--g)}
.links span{color:var(--mu);font-weight:500}
.links small{display:block;font-weight:400;color:var(--mu);margin-top:4px;font-size:13px}
"""


def _when(m):
    try:
        t = datetime.strptime(m.get("updated", ""), "%Y-%m-%d %H:%M UTC")
        return t.strftime("%d %B, %Y").lstrip("0")
    except ValueError:
        return m.get("updated", "")


def _has_stat(m):
    return bool(m.get("passed") and m.get("examinees"))


def _stat(m):
    return f'{m["passed"]:,} of {m["examinees"]:,} passed' if _has_stat(m) else ""


def _excerpt(m):
    if _has_stat(m):
        return (f'The Professional Regulation Commission (PRC) announces that {m["passed"]:,} out of '
                f'{m["examinees"]:,} passed the {m["exam"]} examination given in {m["month"]} {m["year"]}.')
    return f'Official list of passers for the {m["exam"]} examination, {m["month"]} {m["year"]}.'


def _wrap(head, FOOT, title, desc, path, body):
    return head(title, desc, path) + f"<style>{CSS}</style>" + body + FOOT


def results_index(head, FOOT, exams):
    if exams:
        items = "".join(
            f'<li><p class="rdate">{E(_when(d["meta"]))}</p>'
            f'<a class="rtitle" href="/results/{E(d["meta"]["slug"])}/">'
            f'{E(d["meta"]["exam"])} Licensure Examination Results · {E(d["meta"]["month"])} {d["meta"]["year"]}</a>'
            f'<p class="rex">{E(_excerpt(d["meta"]))}</p></li>'
            for d in exams)
        listing = f'<ul class="rlist">{items}</ul>'
    else:
        listing = ('<p class="mu">No results in the last 30 days. Each new release appears here '
                   'as soon as the PRC publishes it.</p>')
    body = f'<h1>Exam Results</h1><p class="mu">Results from the last 30 days, newest first.</p>{listing}'
    return _wrap(head, FOOT, "Exam Results – PH Exam Result",
                 "Recent PRC licensure examination results, newest first.", "results/", body)


def _card(href, label, sub, on):
    if on:
        return f'<a href="{E(href)}">{E(label)}<small>{E(sub)}</small></a>'
    return f'<span>{E(label)}<small>{E(sub)}</small></span>'


def release_hub(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    topn = m.get("topnotchers") or []
    schools = m.get("schools") or []
    cards = (
        _card(f"/{slug}/", "List of Successful Examinees", f'{len(d["passers"]):,} names', True)
        + _card(f"/results/{slug}/topnotchers/", "Topnotchers",
                f"{len(topn)} listed" if topn else "Not published yet", bool(topn))
        + _card(f"/results/{slug}/schools/", "Performance of Schools",
                f"{len(schools)} schools" if schools else "Not published yet", bool(schools))
    )
    stat = f" {_stat(m)}." if _has_stat(m) else ""
    body = (f'<p class="back"><a href="/results/">Back to Exam Results</a></p>'
            f'<h1>{E(m["exam"])}</h1>'
            f'<p class="mu">{E(m["month"])} {m["year"]}.{E(stat)} Released {E(_when(m))}.</p>'
            f'<nav class="links" aria-label="Release sections">{cards}</nav>'
            f'<p class="mu">Source: <a href="{E(m["source"])}" rel="nofollow">official PRC announcement</a>.</p>')
    return _wrap(head, FOOT, f'{m["exam"]} Results · {m["month"]} {m["year"]}',
                 f'Results for {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/", body)


def topnotchers_page(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    rows = m.get("topnotchers") or []
    if rows:
        trs = "".join(
            f'<tr><td>{E(str(r.get("rank", "")))}</td><td>{E(r.get("name", ""))}</td>'
            f'<td>{E(r.get("school", ""))}</td></tr>' for r in rows)
        content = ('<table><thead><tr><th>Rank</th><th>Name</th><th>School</th></tr></thead>'
                   f'<tbody>{trs}</tbody></table>')
    else:
        content = (f'<p class="mu">The topnotchers list for this examination is not on this site yet. '
                   f'Read the <a href="{E(m["source"])}" rel="nofollow">official PRC announcement</a>.</p>')
    body = (f'<p class="back"><a href="/results/{slug}/">Back to {E(m["exam"])}</a></p>'
            f'<h1>Topnotchers</h1><p class="mu">{E(m["exam"])}, {E(m["month"])} {m["year"]}</p>'
            f'<section class="card">{content}</section>')
    return _wrap(head, FOOT, f'Topnotchers · {m["exam"]} {m["month"]} {m["year"]}',
                 f'Topnotchers: {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/topnotchers/", body)


def schools_page(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    rows = m.get("schools") or []
    if rows:
        trs = "".join(
            f'<tr><td>{E(r.get("school", ""))}</td><td>{r.get("takers", ""):,}</td>'
            f'<td>{r.get("passers", ""):,}</td><td>{E(str(r.get("rate", "")))}</td></tr>'
            for r in rows)
        content = ('<table><thead><tr><th>School</th><th>Examinees</th><th>Passers</th><th>Passing rate</th></tr></thead>'
                   f'<tbody>{trs}</tbody></table>')
    else:
        content = (f'<p class="mu">The performance of schools for this examination is not on this site yet. '
                   f'Read the <a href="{E(m["source"])}" rel="nofollow">official PRC announcement</a>.</p>')
    body = (f'<p class="back"><a href="/results/{slug}/">Back to {E(m["exam"])}</a></p>'
            f'<h1>Performance of Schools</h1><p class="mu">{E(m["exam"])}, {E(m["month"])} {m["year"]}</p>'
            f'<section class="card">{content}</section>')
    return _wrap(head, FOOT, f'Performance of Schools · {m["exam"]} {m["month"]} {m["year"]}',
                 f'School performance: {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/schools/", body)


def exam_results_pages(head, FOOT, d):
    """Returns {relative path: html} for one release: hub, topnotchers, schools."""
    slug = d["meta"]["slug"]
    return {
        f"results/{slug}/index.html": release_hub(head, FOOT, d),
        f"results/{slug}/topnotchers/index.html": topnotchers_page(head, FOOT, d),
        f"results/{slug}/schools/index.html": schools_page(head, FOOT, d),
    }
