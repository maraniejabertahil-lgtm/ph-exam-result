"""List page design: A-Z row with search; all names 200 per page with a pager;
one page per letter (200 per page, pager only when more than 200 names);
official-page frame below the names on the first all-names page only.
Follows the site's light/dark mode."""
import html

E = html.escape
PER_PAGE = 200
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

CSS = """
.ex{max-width:900px;margin:0 auto;color:var(--text)}
.ex h1{font-size:1.4rem;margin:8px 0 6px}
.ex .src{color:var(--mu);font-size:14px;margin:0 0 12px}
.ex .src a{color:var(--g2);font-weight:600}
.ex .bar{display:flex;align-items:center;gap:8px}
.ex .letters{flex:1;min-width:0;display:flex;gap:5px;overflow-x:auto;padding:4px 2px 8px;scrollbar-width:thin}
.ex .letters a,.ex .letters span{flex:0 0 auto;min-width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--g2);font:600 13px system-ui;text-decoration:none}
.ex .letters a.on{background:var(--g);border-color:var(--g);color:#fff}
.ex .letters span.off{color:var(--line);border-color:var(--line)}
.ex .sbtn{flex:0 0 auto;width:40px;height:40px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--g);display:flex;align-items:center;justify-content:center;cursor:pointer}
.ex .sbtn[aria-expanded="true"]{background:var(--g);color:#fff;border-color:var(--g)}
.ex .sbtn svg{width:20px;height:20px;fill:currentColor}
.ex .sbox{margin:8px 0}
.ex .sbox[hidden]{display:none}
.ex .sbox input{width:100%;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text);font:inherit}
.ex .mu{color:var(--mu);font-size:14px}
.ex table{width:100%;border-collapse:collapse}
.ex th,.ex td{padding:9px 6px;border-bottom:1px solid var(--line);text-align:left;font-size:15px;color:var(--text)}
.ex th{color:var(--mu);font-weight:600}
.ex td:first-child{width:64px;color:var(--mu)}
.pagerwrap{display:flex;justify-content:flex-end;margin:10px 0 14px}
.pager{display:flex;align-items:center;gap:6px;max-width:100%;font:600 13px system-ui}
.pager .edge{flex:0 0 auto;min-width:34px;height:32px;display:inline-flex;align-items:center;justify-content:center;padding:0 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--g2);text-decoration:none}
.pager .edge.off{color:var(--line);background:transparent}
.pager .nums{display:flex;gap:6px;overflow-x:auto;max-width:170px;padding:2px;scrollbar-width:thin}
.pager .nums a{flex:0 0 auto;min-width:34px;height:32px;display:inline-flex;align-items:center;justify-content:center;padding:0 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--g2);text-decoration:none}
.pager .nums a.on{background:var(--g);border-color:var(--g);color:#fff}
.official{margin:18px 0 8px}
.official .viewer{--page-ratio:1.42;height:calc((min(100vw - 32px, 868px) - 16px) * var(--page-ratio) + 16px);overflow-y:auto;overscroll-behavior:contain;scroll-snap-type:y mandatory;background:#2b2b2b;border-radius:6px;padding:8px;box-sizing:border-box}
.official .pg{scroll-snap-align:start;margin-bottom:8px;background:#fff}
.official .pg:last-child{margin-bottom:0}
.official .pg img{display:block;width:100%;height:auto}
.official .pg.ph{aspect-ratio:1 / var(--page-ratio);display:flex;align-items:center;justify-content:center;text-align:center;padding:16px;color:#5f6b78;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;border:1px dashed #cfd6de;box-sizing:border-box}
@media (max-width:600px){.official .viewer{height:calc((100vw - 32px - 16px) * var(--page-ratio) + 16px)}}
"""

SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

SEARCH_JS = """
(function(){
  var sb=document.getElementById("sb"),box=document.getElementById("sbox"),q=document.getElementById("q"),
      tb=document.getElementById("tb"),c=document.getElementById("c"),orig=tb.innerHTML,all=null;
  if(!sb)return;
  sb.addEventListener("click",function(){var o=box.hidden;box.hidden=!o;sb.setAttribute("aria-expanded",String(o));
    if(o){q.focus();}else{q.value="";tb.innerHTML=orig;c.textContent="";}});
  q.addEventListener("input",async function(){
    var s=q.value.trim().toUpperCase();
    if(!s){tb.innerHTML=orig;c.textContent="";return;}
    if(!all){all=(await (await fetch(DATA_URL)).json()).passers;}
    var r=all.filter(function(x){return x[1].split(",")[0].trim().toUpperCase().indexOf(s)===0;}).slice(0,300);
    c.textContent=r.length+" match(es) across the whole list";
    tb.innerHTML=r.map(function(x){return "<tr><td>"+x[0]+"</td><td>"+x[1].replace(/&/g,"&amp;").replace(/</g,"&lt;")+"</td></tr>";}).join("");
  });
})();
"""


def letter_of(name):
    k = name.split(",")[0].strip()[:1].upper()
    return k if k in LETTERS else "#"


def page_path(slug, letter, n):
    """/slug/ and /slug/2/ for all names; /slug/a/ and /slug/a/2/ for one letter."""
    base = f"/{slug}/" + (f"{letter.lower()}/" if letter else "")
    return base if n == 1 else f"{base}{n}/"


def page_count(rows):
    return max(1, -(-len(rows) // PER_PAGE))


def letter_row(slug, rows, active=None):
    present = {letter_of(name) for _, name in rows}
    out = []
    for L in LETTERS:
        if L in present:
            cls = ' class="on"' if L == active else ""
            out.append(f'<a href="{page_path(slug, L, 1)}"{cls}>{L}</a>')
        else:
            out.append(f'<span class="off">{L}</span>')
    return '<nav class="letters" aria-label="Letters">' + "".join(out) + "</nav>"


def pager(slug, letter, n, total):
    """Back and Next stay fixed at the ends. Only the page numbers scroll sideways between them.
    Hidden when there is only one page (200 names or fewer)."""
    if total <= 1:
        return ""
    back = (f'<a class="edge" href="{page_path(slug, letter, n - 1)}" aria-label="Previous page">‹ Back</a>'
            if n > 1 else '<span class="edge off" aria-hidden="true">‹ Back</span>')
    nxt = (f'<a class="edge" href="{page_path(slug, letter, n + 1)}" aria-label="Next page">Next ›</a>'
           if n < total else '<span class="edge off" aria-hidden="true">Next ›</span>')
    nums = "".join(
        f'<a href="{page_path(slug, letter, i)}"{" class=\"on\"" if i == n else ""}>{i}</a>'
        for i in range(1, total + 1))
    return ('<div class="pagerwrap"><nav class="pager" aria-label="Name pages">'
            f'{back}<div class="nums">{nums}</div>{nxt}</nav></div>')


def name_table(part):
    return "".join(f"<tr><td>{num}</td><td>{E(name)}</td></tr>" for num, name in part)


def official_frame(scans):
    """Frame of official PRC page screenshots. Shown on the first all-names page only.
    Until the pipeline supplies scans, one empty page-shaped placeholder shows the design."""
    if scans:
        pages = "".join(
            f'<div class="pg"><img src="{E(u)}" alt="Official PRC roll, page {i} of {len(scans)}" '
            f'loading="lazy" decoding="async"></div>'
            for i, u in enumerate(scans, 1))
    else:
        pages = ('<div class="pg ph">Official PRC pages appear here.<br>'
                 'The screenshots are added automatically after each release.</div>')
    return ('<section class="official" aria-label="Official PRC pages">'
            f'<div class="viewer">{pages}</div>'
            '<p class="mu">Screenshots of the official PRC roll. Source: Official PRC announcement.</p>'
            "</section>")


def page_html(head, FOOT, m, rows, letter, vrows, n, frame=""):
    """One page. letter=None means all names; vrows are the names shown on this view."""
    slug, exam = m["slug"], m["exam"]
    total = page_count(vrows)
    part = vrows[(n - 1) * PER_PAGE: n * PER_PAGE]
    title = f'{exam} Results: {m["month"]} {m["year"]} List of Passers'
    if letter:
        title += f" · Names starting with {letter}"
    if n > 1:
        title += f" (page {n})"
    search_btn = ('<button class="sbtn" id="sb" type="button" aria-expanded="false" aria-label="Search names">'
                  + SEARCH_SVG + "</button>")
    search_box = ('<section class="sbox" id="sbox" hidden>'
                  '<input id="q" type="search" placeholder="Type a passer\'s first name…" autocomplete="off">'
                  '<p class="mu" id="c"></p></section>')
    body = (
        f'<style>{CSS}</style>'
        '<div class="ex">'
        f'<h1>{E(title)}</h1>'
        f'<p class="src">Source: <a href="{E(m["source"])}" rel="nofollow">Official PRC announcement</a></p>'
        f'<div class="bar">{letter_row(slug, rows, letter)}{search_btn}</div>'
        f'{search_box}'
        '<section><table><thead><tr><th>Seq. No.</th><th>Name</th></tr></thead>'
        f'<tbody id="tb">{name_table(part)}</tbody></table></section>'
        f'{pager(slug, letter, n, total)}'
        f'{frame}'
        f'<script>var DATA_URL="/data/{slug}.json";{SEARCH_JS}</script>'
        '</div>'
    )
    path = page_path(slug, letter, n).strip("/") + "/"
    return head(title, f'Official list of passers: {exam}, {m["month"]} {m["year"]}.', path) + body + FOOT


def write_list_pages(write, head, FOOT, m, rows, scans=None):
    """Writes every page of one list (all names, then each letter that has names).
    Returns the site paths, for the sitemap."""
    urls = []
    views = [(None, rows)] + [(L, [r for r in rows if letter_of(r[1]) == L]) for L in LETTERS]
    for letter, vrows in views:
        if letter and not vrows:
            continue
        for n in range(1, page_count(vrows) + 1):
            frame = official_frame(scans) if (letter is None and n == 1) else ""
            p = page_path(m["slug"], letter, n)
            write(p.lstrip("/") + "index.html", page_html(head, FOOT, m, rows, letter, vrows, n, frame))
            urls.append(p)
    return urls
