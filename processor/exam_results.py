"""Exam Results: release list (/results/), a hub per release (/results/<slug>/),
and the Topnotchers and Performance of Schools pages. Same look as Home (pages.shell)."""
import html
from datetime import datetime
from pages import shell, tile, TABLE_CSS

E = html.escape


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


ddef results_index(head, FOOT, exams):
    if exams:
        inner = '<div class="grid">' + "".join(
            tile("list",
                 f'{d["meta"]["exam"]} · {d["meta"]["month"]} {d["meta"]["year"]}',
                 f'{_when(d["meta"])}. {_excerpt(d["meta"])}',
                 "View results", f'/results/{d["meta"]["slug"]}/')
            for d in exams) + "</div>"
    else:
        inner = ('<p class="sub">No results in the last 30 days. Each new release appears here '
                 'as soon as the PRC publishes it.</p>')
    return shell(head, FOOT, "Exam Results – PH Exam Result",
                 "Recent PRC licensure examination results, newest first.", "results/",
                 "", "Exam Results", "Results from the last 30 days, newest first.", inner,
                 main_page=True)


def release_hub(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    topn = m.get("topnotchers") or []
    schools = m.get("schools") or []
    cards = (
        '<div class="grid">'
        + tile("list", "List of Successful Examinees", f'{len(d["passers"]):,} names', "Open", f"/{slug}/")
        + (tile("star", "Topnotchers", f"{len(topn)} listed", "Open", f"/results/{slug}/topnotchers/")
           if topn else tile("star", "Topnotchers", "Not published yet"))
        + (tile("school", "Performance of Schools", f"{len(schools)} schools", "Open", f"/results/{slug}/schools/")
           if schools else tile("school", "Performance of Schools", "Not published yet"))
        + "</div>")
    sub = f'{m["month"]} {m["year"]}.' + (f' {_stat(m)}.' if _has_stat(m) else "") + f' Released {_when(m)}.'
    inner = (cards
             + f'<p class="sub"><a href="{E(m["source"])}" rel="nofollow">Official PRC announcement</a></p>'
             + '<a class="btn" href="/results/">Back to Exam Results</a>')
    return shell(head, FOOT, f'{m["exam"]} Results · {m["month"]} {m["year"]}',
                 f'Results for {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/",
                 "RELEASE", m["exam"], sub, inner)


def topnotchers_page(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    rows = m.get("topnotchers") or []
    if rows:
        trs = "".join(
            f'<tr><td>{E(str(r.get("rank", "")))}</td><td>{E(str(r.get("name", "")))}</td>'
            f'<td>{E(str(r.get("school", "")))}</td></tr>' for r in rows)
        inner = ('<div class="tablecard"><table><thead><tr><th>Rank</th><th>Name</th><th>School</th></tr></thead>'
                 f'<tbody>{trs}</tbody></table></div>')
    else:
        inner = (f'<p class="sub">The topnotchers list is not on this site yet. Read the '
                 f'<a href="{E(m["source"])}" rel="nofollow">official PRC announcement</a>.</p>')
    inner += f'<a class="btn" href="/results/{slug}/">Back to {E(m["exam"])}</a>'
    return shell(head, FOOT, f'Topnotchers · {m["exam"]} {m["month"]} {m["year"]}',
                 f'Topnotchers: {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/topnotchers/",
                 "TOPNOTCHERS", "Topnotchers", f'{m["exam"]}, {m["month"]} {m["year"]}', inner, TABLE_CSS)


def schools_page(head, FOOT, d):
    m = d["meta"]
    slug = m["slug"]
    rows = m.get("schools") or []
    if rows:
        trs = "".join(
            f'<tr><td>{E(str(r.get("school", "")))}</td><td>{E(str(r.get("takers", "")))}</td>'
            f'<td>{E(str(r.get("passers", "")))}</td><td>{E(str(r.get("rate", "")))}</td></tr>' for r in rows)
        inner = ('<div class="tablecard"><table><thead><tr><th>School</th><th>Examinees</th>'
                 '<th>Passers</th><th>Passing rate</th></tr></thead>'
                 f'<tbody>{trs}</tbody></table></div>')
    else:
        inner = (f'<p class="sub">The performance of schools is not on this site yet. Read the '
                 f'<a href="{E(m["source"])}" rel="nofollow">official PRC announcement</a>.</p>')
    inner += f'<a class="btn" href="/results/{slug}/">Back to {E(m["exam"])}</a>'
    return shell(head, FOOT, f'Performance of Schools · {m["exam"]} {m["month"]} {m["year"]}',
                 f'School performance: {m["exam"]}, {m["month"]} {m["year"]}.', f"results/{slug}/schools/",
                 "PERFORMANCE", "Performance of Schools", f'{m["exam"]}, {m["month"]} {m["year"]}', inner, TABLE_CSS)


def exam_results_pages(head, FOOT, d):
    """Returns {relative path: html} for one release: hub, topnotchers, schools."""
    slug = d["meta"]["slug"]
    return {
        f"results/{slug}/index.html": release_hub(head, FOOT, d),
        f"results/{slug}/topnotchers/index.html": topnotchers_page(head, FOOT, d),
        f"results/{slug}/schools/index.html": schools_page(head, FOOT, d),
    }
