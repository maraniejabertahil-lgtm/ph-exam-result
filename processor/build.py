"""Builds the static website in /site from /data (no server needed).

Public homepage: A-Z row + search (matches the FIRST NAME, the text before the comma),
one examination at a time (selector shows name and release date), 30-day retention.
Owner page: processor/owner.html is copied to /owner/ (Firebase sign-in, owner only).
"""
import json, html, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pages import landing_page, static_pages
from study_tips import study_tips_page
from upcoming import upcoming_page, build_status, home_redirect_script
from exam_results import results_index, exam_results_pages

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
SITE = ROOT / "site"
E = html.escape
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
RETENTION = timedelta(days=int(CFG.get("retention_days", 30)))
FB_URL = CFG.get("facebook_url") or "https://www.facebook.com/"
OWNER_URL = CFG.get("owner_url") or "#"          # set to https://ph-exam-result.pages.dev/owner/ in config.json
NOW = datetime.now(timezone.utc)
STAMP = "%Y-%m-%d %H:%M UTC"

CSS = """@import url('https://fonts.googleapis.com/css2?family=Caveat:wght@700&family=Plus+Jakarta+Sans:wght@500;700&display=swap');:root{--bg:#f5f7f6;--card:#fff;--text:#16211b;--mu:#5f6d65;--line:#dfe6e2;--g:#22b35e;--g2:#17924a;--gbg:#e8f7ee}
@media(prefers-color-scheme:dark){:root{--bg:#0f1512;--card:#17201b;--text:#e7efe9;--mu:#9baba1;--line:#27342d;--g:#2fc76e;--g2:#25a85a;--gbg:#173225}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--g2)}
.top{background:var(--card);border-bottom:1px solid var(--line);position:relative;padding:12px 56px 10px;text-align:center}
.fb{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--g);color:#fff}
.fb svg{width:12px;height:12px;fill:currentColor}
.brand{display:block;margin-top:4px;font-weight:700;font-size:1.25rem;color:var(--text);text-decoration:none}
.login{position:absolute;right:14px;top:12px;width:40px;height:40px;border-radius:50%;border:1px solid var(--line);background:var(--card);color:var(--g);display:flex;align-items:center;justify-content:center}
.login svg,.sbtn svg{width:20px;height:20px;fill:currentColor}
.wrap{max-width:900px;margin:0 auto;padding:14px 16px 8px}
.bar{display:flex;align-items:center;gap:8px}
.letters{flex:1;min-width:0;display:flex;gap:5px;overflow-x:auto;overflow-y:hidden;padding:4px 2px 8px;scrollbar-width:thin;-webkit-overflow-scrolling:touch}
.letters button{flex:0 0 auto;min-width:30px;height:30px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--text);font:600 12px system-ui;cursor:pointer}
.letters button:hover{border-color:var(--g)}
.letters button.on{background:var(--g);border-color:var(--g);color:#fff}
.sbtn{flex:0 0 auto;width:40px;height:40px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--g);display:flex;align-items:center;justify-content:center;cursor:pointer}
.sbtn[aria-expanded="true"]{background:var(--g);color:#fff;border-color:var(--g)}
.sbox{margin:6px 0 4px}
.sbox[hidden]{display:none}
input{width:100%;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text);font:inherit}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}
h1{font-size:1.4rem;margin:8px 0}
h2{font-size:1.15rem;margin:6px 0 4px}
.exsel{width:100%;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text);font:600 15px system-ui;margin-bottom:8px}
.mu{color:var(--mu);font-size:14px}
.names{list-style:none;margin:0;padding:0}
.names li{padding:10px 4px;border-bottom:1px solid var(--line);word-break:break-word;font-size:15px}
.names li:last-child{border-bottom:none}
.empty{color:var(--mu);text-align:center;padding:24px 0;font-size:15px}
.res a{font-weight:600;text-decoration:none}
table{width:100%;border-collapse:collapse}
td,th{padding:7px;border-bottom:1px solid var(--line);text-align:left;font-size:15px}
td:first-child{width:70px;color:var(--mu)}
.tabs a{display:inline-block;padding:5px 12px;border:1px solid var(--line);border-radius:99px;margin:2px;text-decoration:none}
footer{color:var(--mu);font-size:12px;text-align:center;padding:24px 0 40px}
.site-header{background:var(--card);border-bottom:1px solid var(--line);font-family:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",sans-serif}
.site-header .brand{display:flex;align-items:center;justify-content:center;gap:.35rem;padding:24px 16px 20px;text-decoration:none;color:var(--text);margin:0}
.brand__mark{font-family:"Caveat",cursive;font-size:3rem;line-height:1;font-weight:700;display:inline-flex}
.brand__mark .p{color:#0a7cff}
.brand__mark .h{color:#e8590c}
.brand__name{font-size:clamp(1.5rem,4vw,2.1rem);font-weight:700;letter-spacing:-.01em;white-space:nowrap}
.nav{border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.nav__list{list-style:none;margin:0;padding:0 16px;display:flex;justify-content:center;gap:clamp(1.25rem,4vw,3.25rem);overflow-x:auto;scrollbar-width:none}
.nav__list::-webkit-scrollbar{display:none}
.nav__link{display:block;position:relative;padding:16px 0 17px;font-size:1.05rem;font-weight:500;color:var(--text);text-decoration:none;white-space:nowrap}
.nav__link:hover{color:#0a7cff}
.nav__link[aria-current="page"]{color:#0a7cff;font-weight:700}
.nav__link[aria-current="page"]::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:4px;border-radius:4px 4px 0 0;background:#0a7cff}
.nav__link:focus-visible,.site-header .brand:focus-visible{outline:3px solid #0a7cff;outline-offset:4px;border-radius:4px}
@media(max-width:640px){.brand__mark{font-size:2.4rem}.nav__link{font-size:.98rem}.nav__list{justify-content:flex-start}}
"""

FB_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 22v-8h2.7l.4-3.2h-3.1V8.8c0-.9.3-1.6 1.6-1.6h1.7V4.3c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.3H7.3V14h2.8v8h3.4z"/></svg>'
USER_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zm0 2c-4.2 0-8 2.1-8 5v2h16v-2c0-2.9-3.8-5-8-5z"/></svg>'
SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

# Homepage script. EXAMS (the examination list) is written in front of it by main().
INDEX_JS = """
const LET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const $ = id => document.getElementById(id);
const first = n => n.split(",")[0].trim().toUpperCase();   // first name = text before the comma
let exam = EXAMS.length ? EXAMS[0].slug : "", cur = "A", q = "", cache = {};
function mk(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
async function getLetter(L) {
  const key = exam + "/" + L;
  if (!cache[key]) { try { cache[key] = await (await fetch("/letters/" + exam + "/" + L + ".json")).json(); } catch (e) { cache[key] = []; } }
  return cache[key];
}
async function allNames() {
  return (await Promise.all(LET.map(getLetter))).flat();
}
function closeSearch() { $("sbox").hidden = true; $("sb").setAttribute("aria-expanded", "false"); }
function buildExamSelect() {
  const sel = $("exsel");
  for (const e of EXAMS) { const o = mk("option", e.label + " \\u00b7 Released " + e.released); o.value = e.slug; sel.appendChild(o); }
  sel.onchange = () => { exam = sel.value; cur = "A"; q = ""; $("q").value = ""; closeSearch(); render(); };
  if (!EXAMS.length) sel.hidden = true;
}
function buildLetters() {
  const bar = $("letters");
  for (const L of LET) {
    const b = mk("button", L); b.type = "button"; b.dataset.l = L;
    b.onclick = () => { cur = L; q = ""; $("q").value = ""; closeSearch(); render(); };
    bar.appendChild(b);
  }
}
async function render() {
  for (const b of document.querySelectorAll("#letters button")) {
    const on = !q && b.dataset.l === cur;
    b.classList.toggle("on", on);
    if (on) b.scrollIntoView({ inline: "nearest", block: "nearest" });
  }
  let items = [], head;
  if (!exam) {
    head = "No results in the last 30 days";
  } else if (q) {
    const Q = q.toUpperCase();
    items = (await allNames()).filter(n => first(n).startsWith(Q)).slice(0, 300);
    head = "Search: \\u201c" + q + "\\u201d";
  } else {
    items = await getLetter(cur);
    head = "Letter " + cur;
  }
  $("hd").textContent = head;
  $("cnt").textContent = items.length ? items.length + " name(s)" : "";
  $("none").textContent = q ? "No passer's first name starts with that." : "No names published for this letter yet.";
  $("none").hidden = items.length > 0;
  $("names").replaceChildren(...items.map(n => mk("li", n)));
}
buildExamSelect();
buildLetters();
$("sb").onclick = () => {
  const open = $("sbox").hidden;
  $("sbox").hidden = !open;
  $("sb").setAttribute("aria-expanded", String(open));
  if (open) $("q").focus(); else { q = ""; $("q").value = ""; render(); }
};
$("q").addEventListener("input", () => { q = $("q").value.trim(); render(); });
render();
"""

# Examination page script: search by first name, same rule as the homepage.
EXAM_JS = """
var q=document.getElementById("q"),tb=document.getElementById("tb"),c=document.getElementById("c"),orig=tb.innerHTML,all=null;
q.addEventListener("input",async function(){
  var s=q.value.trim().toUpperCase();
  if(!s){tb.innerHTML=orig;c.textContent="";return}
  if(!all)all=(await (await fetch(DATA_URL)).json()).passers;
  var r=all.filter(function(x){return x[1].split(",")[0].trim().toUpperCase().indexOf(s)===0}).slice(0,300);
  c.textContent=r.length+" match(es)";
  tb.innerHTML=r.map(function(x){return"<tr><td>"+x[0]+"</td><td>"+x[1].replace(/&/g,"&amp;").replace(/</g,"&lt;")+"</td></tr>"}).join("");
});
"""


def parse(stamp):
    try:
        return datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def live(meta):
    """True while a result is within the retention window (default 30 days after processing)."""
    t = parse(meta.get("updated")) or NOW
    return NOW - t <= RETENTION


def released(meta):
    t = parse(meta.get("updated"))
    return t.strftime("%b %d, %Y") if t else meta.get("updated", "")
  
def site_header(path=""):
    home = ' aria-current="page"' if path == "" else ""
    return (
        '<header class="site-header">'
        '<a class="brand" href="/"><span class="brand__mark" aria-hidden="true"><span class="p">P</span><span class="h">H</span></span><span class="brand__name">Exam Result</span></a>'
        '<nav class="nav" aria-label="Main"><ul class="nav__list">'
        f'<li><a class="nav__link" href="/?home=1"{home}>Home</a></li>'
        '<li><a class="nav__link" href="/upcoming/">Upcoming Release</a></li>'
        '<li><a class="nav__link" href="/results/">Exam Results</a></li>'
        '<li><a class="nav__link" href="/study-tips/">Study Tips</a></li>'
        '<li><a class="nav__link" href="/books/">Books</a></li>'
        '</ul></nav></header>')

def head(title, desc, path=""):
    ga = (f'<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token":"{CFG["cf_beacon"]}"}}\'></script>'
          if CFG.get("cf_beacon") else "")
    ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={CFG["adsense_client"]}" crossorigin="anonymous"></script>'
           if CFG.get("adsense_client") else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<title>{E(title)}</title><meta name="description" content="{E(desc)}">'
            f'<link rel="canonical" href="{CFG["site_url"]}/{path}"><style>{CSS}</style>{ga}{ads}</head><body>'
            f'{site_header(path)}<main class="wrap">')


FOOT = (f'</main><footer>Independent site, not affiliated with PRC. Source: Professional Regulation Commission (prc.gov.ph). '
        f'Always verify at online.prc.gov.ph. Name corrections/removal: {E(CFG["contact_email"])}.</footer></body></html>')


def write(rel, content):
    p = SITE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def groups(rows):
    if len(rows) <= 3000:
        return [("all", "", rows)]
    spans = [("a-f", "A–F", "ABCDEF"), ("g-l", "G–L", "GHIJKL"), ("m-r", "M–R", "MNOPQR"), ("s-z", "S–Z", "STUVWXYZ")]
    return [(k, lab, [r for r in rows if r[1][:1].upper() in set(ls) or (k == "s-z" and not r[1][:1].isalpha())])
            for k, lab, ls in spans]


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)

    raw = []
    for p in (ROOT / "data").glob("*.json"):
        if p.stem in ("state", "releases"):
            continue
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict) and "meta" in data:
                raw.append(data)
        except Exception as e:
            print(f"Skipping malformed JSON {p.name}: {e}")

    # Every published result, official lists included, leaves the site after the retention window.
    exams = [d for d in raw if live(d["meta"])]
    exams.sort(key=lambda d: d["meta"].get("updated", ""), reverse=True)
    print(f"{len(exams)} live result(s), {len(raw) - len(exams)} past the {RETENTION.days}-day window")

    state_f = ROOT / "data" / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"upcoming": []}

    exam_list, urls = [], ["/"]
    for d in exams:
        m, rows = d["meta"], d["passers"]
        label = f'{m["exam"]} · {m["month"]} {m["year"]}'
        shutil.copy(ROOT / "data" / f'{m["slug"]}.json', SITE / "data" / f'{m["slug"]}.json')

        # Letter files for this examination only (one examination is shown at a time)
        per = {L: [] for L in LETTERS}
        for _, nm in rows:
            k = nm.split(",")[0].strip()[:1].upper()
            if k in per:
                per[k].append(nm)
        for L in LETTERS:
            per[L].sort()
            write(f'letters/{m["slug"]}/{L}.json', json.dumps(per[L], ensure_ascii=False, separators=(",", ":")))
        exam_list.append({"slug": m["slug"], "label": label, "released": released(m)})

        # Examination page
        title = f'{m["exam"]} Results: {m["month"]} {m["year"]} List of Passers'
        for key, lab, part in groups(rows):
            rel = f'{m["slug"]}/' + ("" if key == "all" else f"{key}/")
            tabs = "" if key == "all" else '<div class="tabs">' + "".join(
                f'<a href="/{m["slug"]}/{k}/">{l}</a>' for k, l, _ in groups(rows)) + "</div>"
            trs = "".join(f"<tr><td>{n}</td><td>{E(nm)}</td></tr>" for n, nm in part)
            stat = f'{m["passed"]:,} of {m["examinees"]:,} passed. ' if m.get("passed") and m.get("examinees") else ""
            body = (head(title + (f" ({lab})" if lab else ""), f'Official list of passers: {m["exam"]}, {m["month"]} {m["year"]}.', rel)
                    + f'<h1>{E(title)}</h1><p class="mu">{stat}Updated {E(m["updated"])} · '
                    f'<a href="{E(m["source"])}" rel="nofollow">Official PRC announcement</a></p>{tabs}'
                    f'<section class="card"><div class="sbox"><input id="q" type="search" placeholder="Type a passer\'s first name…" autocomplete="off"></div>'
                    f'<p class="mu" id="c"></p></section>'
                    f'<section class="card"><table><thead><tr><th>#</th><th>Name</th></tr></thead>'
                    f'<tbody id="tb">{trs}</tbody></table></section>'
                    f'<script>var DATA_URL="/data/{m["slug"]}.json";' + EXAM_JS + '</script>' + FOOT)
            write(rel + "index.html", body)
            urls.append("/" + rel)

    for d in exams:
        for rel, doc in exam_results_pages(head, FOOT, d).items():
            write(rel, doc)
            urls.append("/" + rel.replace("index.html", ""))

    # Homepage. The examination list is embedded so the selector works without a request.
    exams_json = json.dumps(exam_list, ensure_ascii=False).replace("</", "<\\/")
    def _up(u):
        when = u.get("release_date_text") or u.get("release_date") or u.get("release_within") or "Results usually post within days of the last exam day."
        tag = {"delayed": " · ⚠️ Delayed/postponed", "released": " · Released"}.get(u.get("status"), "")
        ttl = f'{u.get("exam", "")} – {u.get("month", "")} {u.get("year") or ""}'.strip(" –")
        return (f'<div class="card"><b>{E(ttl)}</b><br><span class="mu">Target release: {E(when)}{tag}</span>'
                f'<br><a href="{E(u.get("url", "#"))}" rel="nofollow">Official PRC announcement</a></div>')
    up = "".join(_up(u) for u in state.get("upcoming", [])) or '<p class="mu">No upcoming release detected right now.</p>'
    lt = "".join(
        f'<div class="card res"><a href="/{E(d["meta"]["slug"])}/">{E(d["meta"]["exam"])} Results: '
        f'{E(d["meta"]["month"])} {d["meta"]["year"]}</a><br>'
        f'<span class="mu">{(d["meta"].get("passed") or d["meta"].get("count", 0)):,} passers · {E(d["meta"]["updated"])}</span></div>'
        for d in exams) or '<p class="mu">Waiting for the next official release…</p>'

    write("results/index.html", results_index(head, FOOT, exams))
    urls.append("/results/")
    write("index.html", landing_page(head, FOOT, CFG).replace("</body>", home_redirect_script() + "</body>"))
    status = build_status(state, exams)
    write("status.json", json.dumps(status, ensure_ascii=False))
    write("upcoming/index.html", upcoming_page(head, FOOT, INDEX_JS, exams_json, status))
    urls.append("/upcoming/")
    write("study-tips/index.html", study_tips_page(head, FOOT))
    urls.append("/study-tips/")

    for rel, doc in static_pages(head, FOOT, CFG).items():
        write(rel, doc)
        urls.append("/" + rel.replace("index.html", ""))

    write("robots.txt", f'User-agent: *\nAllow: /\nSitemap: {CFG["site_url"]}/sitemap.xml\n')
    write("sitemap.xml", '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f'<url><loc>{CFG["site_url"]}{u}</loc></url>' for u in urls) + "</urlset>")
    rel = ROOT / "data" / "releases.json"
    if rel.exists():
        shutil.copy(rel, SITE / "data" / "releases.json")

    # Owner page: Firebase sign-in and dashboard (processor/owner.html), served at /owner/
    owner_src = ROOT / "processor" / "owner.html"
    if owner_src.exists():
        (SITE / "owner").mkdir(parents=True, exist_ok=True)
        shutil.copy(owner_src, SITE / "owner" / "index.html")
    else:
        print("WARNING: processor/owner.html not found, /owner/ was not built")

    print("built", len(urls), "pages")


if __name__ == "__main__":
    main()
