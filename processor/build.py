"""Builds the static website in /site from /data (no server needed).

Design: same as the PH EXAM RESULT owner design (A-Z letter row, search icon,
Facebook icon top centre, login icon top right). Every published result is
hidden 30 days after it was processed (config.json: retention_days).
"""
import json, html, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
SITE = ROOT / "site"
E = html.escape
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
RETENTION = timedelta(days=int(CFG.get("retention_days", 30)))
FB_URL = CFG.get("facebook_url") or "https://www.facebook.com/"
OWNER_URL = CFG.get("owner_url") or "#"          # set to your private dashboard link when you have it
NOW = datetime.now(timezone.utc)

CSS = """:root{--bg:#f5f7f6;--card:#fff;--text:#16211b;--mu:#5f6d65;--line:#dfe6e2;--g:#22b35e;--g2:#17924a;--gbg:#e8f7ee}
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
.mu{color:var(--mu);font-size:14px}
.names{list-style:none;margin:0;padding:0}
.names li{padding:10px 4px;border-bottom:1px solid var(--line);word-break:break-word;font-size:15px}
.names li:last-child{border-bottom:none}
.names .ex{display:block;color:var(--mu);font-size:12px}
.empty{color:var(--mu);text-align:center;padding:24px 0;font-size:15px}
.res a{font-weight:600;text-decoration:none}
table{width:100%;border-collapse:collapse}
td,th{padding:7px;border-bottom:1px solid var(--line);text-align:left;font-size:15px}
td:first-child{width:70px;color:var(--mu)}
.tabs a{display:inline-block;padding:5px 12px;border:1px solid var(--line);border-radius:99px;margin:2px;text-decoration:none}
footer{color:var(--mu);font-size:12px;text-align:center;padding:24px 0 40px}
"""

FB_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 22v-8h2.7l.4-3.2h-3.1V8.8c0-.9.3-1.6 1.6-1.6h1.7V4.3c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.3H7.3V14h2.8v8h3.4z"/></svg>'
USER_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zm0 2c-4.2 0-8 2.1-8 5v2h16v-2c0-2.9-3.8-5-8-5z"/></svg>'
SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

INDEX_JS = """
const LET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const $ = id => document.getElementById(id);
let cur = "A", q = "", cache = {}, every = null;
function mk(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
async function getLetter(L) {
  if (!cache[L]) { try { cache[L] = await (await fetch("/letters/" + L + ".json")).json(); } catch (e) { cache[L] = []; } }
  return cache[L];
}
async function allNames() {
  if (!every) every = (await Promise.all(LET.map(getLetter))).flat();
  return every;
}
function closeSearch() { $("sbox").hidden = true; $("sb").setAttribute("aria-expanded", "false"); }
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
  let items, head;
  if (q) {
    const Q = q.toUpperCase();
    items = (await allNames()).filter(r => r[0].toUpperCase().includes(Q)).slice(0, 300);
    head = "Search: \u201c" + q + "\u201d";
  } else {
    items = await getLetter(cur);
    head = "Letter " + cur;
  }
  $("hd").textContent = head;
  $("cnt").textContent = items.length ? items.length + " name(s)" : "";
  $("none").textContent = q ? "No passer matches that name." : "No names published for this letter yet.";
  $("none").hidden = items.length > 0;
  $("names").replaceChildren(...items.map(r => { const li = mk("li", r[0]); li.appendChild(mk("span", r[1], "ex")); return li; }));
}
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

EXAM_JS = """
var q=document.getElementById("q"),tb=document.getElementById("tb"),c=document.getElementById("c"),orig=tb.innerHTML,all=null;
q.addEventListener("input",async function(){
  var s=q.value.trim().toUpperCase();
  if(!s){tb.innerHTML=orig;c.textContent="";return}
  if(!all)all=(await (await fetch(DATA_URL)).json()).passers;
  var r=all.filter(function(x){return x[1].toUpperCase().indexOf(s)>-1}).slice(0,300);
  c.textContent=r.length+" match(es)";
  tb.innerHTML=r.map(function(x){return"<tr><td>"+x[0]+"</td><td>"+x[1].replace(/&/g,"&amp;").replace(/</g,"&lt;")+"</td></tr>"}).join("");
});
"""


def live(meta):
    """True while a result is still within the retention window (default 30 days)."""
    try:
        t = datetime.strptime(meta["updated"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        t = NOW
    return NOW - t <= RETENTION


def head(title, desc, path=""):
    ga = (f'<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token":"{CFG["cf_beacon"]}"}}\'></script>'
          if CFG.get("cf_beacon") else "")
    ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={CFG["adsense_client"]}" crossorigin="anonymous"></script>'
           if CFG.get("adsense_client") else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<title>{E(title)}</title><meta name="description" content="{E(desc)}">'
            f'<link rel="canonical" href="{CFG["site_url"]}/{path}"><style>{CSS}</style>{ga}{ads}</head><body>'
            f'<header class="top">'
            f'<a class="fb" href="{E(FB_URL)}" target="_blank" rel="noopener" aria-label="Facebook Page">{FB_SVG}</a>'
            f'<a class="brand" href="/">{E(CFG["site_name"])}</a>'
            f'<a class="login" href="{E(OWNER_URL)}" aria-label="Login">{USER_SVG}</a>'
            f'</header><main class="wrap">')


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

    letters = {L: [] for L in LETTERS}
    urls = ["/"]
    for d in exams:
        m, rows = d["meta"], d["passers"]
        label = f'{m["exam"]} · {m["month"]} {m["year"]}'
        shutil.copy(ROOT / "data" / f'{m["slug"]}.json', SITE / "data" / f'{m["slug"]}.json')

        # A–Z index: the first name is the text before the comma
        for _, nm in rows:
            k = nm.split(",")[0].strip()[:1].upper()
            if k in letters:
                letters[k].append([nm, label])

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
                    f'<section class="card"><div class="sbox"><input id="q" type="search" placeholder="Type a passer name…" autocomplete="off"></div>'
                    f'<p class="mu" id="c"></p></section>'
                    f'<section class="card"><table><thead><tr><th>#</th><th>Name</th></tr></thead>'
                    f'<tbody id="tb">{trs}</tbody></table></section>'
                    f'<script>var DATA_URL="/data/{m["slug"]}.json";' + EXAM_JS + '</script>' + FOOT)
            write(rel + "index.html", body)
            urls.append("/" + rel)

    # Letter files used by the A–Z row and search on the homepage
    for L in LETTERS:
        letters[L].sort(key=lambda r: r[0])
        write(f"letters/{L}.json", json.dumps(letters[L], ensure_ascii=False, separators=(",", ":")))

    up = "".join(
        f'<div class="card"><b>{E(u["exam"])} – {E(u["month"])} {u["year"]}</b><br>'
        f'<span class="mu">Results usually post within days of the last exam day.</span></div>'
        for u in state.get("upcoming", [])) or '<p class="mu">No upcoming release detected right now.</p>'
    lt = "".join(
        f'<div class="card res"><a href="/{E(d["meta"]["slug"])}/">{E(d["meta"]["exam"])} Results: '
        f'{E(d["meta"]["month"])} {d["meta"]["year"]}</a><br>'
        f'<span class="mu">{(d["meta"].get("passed") or d["meta"].get("count", 0)):,} passers · {E(d["meta"]["updated"])}</span></div>'
        for d in exams) or '<p class="mu">Waiting for the next official release…</p>'

    index = (head(f'{CFG["site_name"]} – Board Exam Results', "Official list of passers, A to Z, auto-updated from PRC releases.")
             + '<div class="bar"><nav class="letters" id="letters" aria-label="Choose a letter"></nav>'
             + f'<button class="sbtn" id="sb" type="button" aria-label="Search passer name" aria-expanded="false">{SEARCH_SVG}</button></div>'
             + '<div class="sbox" id="sbox" hidden><input id="q" type="search" placeholder="Type a passer name…" autocomplete="off"></div>'
             + '<section class="card"><h2 id="hd">Letter A</h2><p class="mu" id="cnt"></p>'
             + '<ul class="names" id="names"></ul><p class="empty" id="none" hidden></p></section>'
             + f'<section><h2 id="upcoming">Upcoming release</h2>{up}</section>'
             + f'<section><h2 id="latest">Latest results</h2>{lt}</section>'
             + f'<script>{INDEX_JS}</script>' + FOOT)
    write("index.html", index)

    write("about/index.html", head("About", "About this site", "about/")
          + '<h1>About · Disclaimer · Privacy</h1>'
          + '<p>This site republishes publicly released lists of successful examinees from the PRC, automatically. '
          + f'Results are removed {RETENTION.days} days after they are processed. It is not affiliated with PRC.</p>'
          + f'<p>Contact: {E(CFG["contact_email"])}</p>' + FOOT)
    urls.append("/about/")

    write("robots.txt", f'User-agent: *\nAllow: /\nSitemap: {CFG["site_url"]}/sitemap.xml\n')
    write("sitemap.xml", '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f'<url><loc>{CFG["site_url"]}{u}</loc></url>' for u in urls) + "</urlset>")
    rel = ROOT / "data" / "releases.json"
    if rel.exists():
        shutil.copy(rel, SITE / "data" / "releases.json")
    print("built", len(urls), "pages")


if __name__ == "__main__":
    main()
