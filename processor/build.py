"""Builds the static website in /site from /data (no server needed)."""
import json, html, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
SITE = ROOT / "site"
E = html.escape
CSS = """:root{--bg:#f7f8fa;--c:#fff;--t:#1a2230;--m:#5d6778;--l:#e1e5ec;--a:#0b6e4f}
@media(prefers-color-scheme:dark){:root{--bg:#10141b;--c:#181e28;--t:#e8ecf2;--m:#98a3b5;--l:#2a3342;--a:#3ecf9a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:16px/1.5 system-ui,sans-serif}
.w{max-width:900px;margin:auto;padding:0 16px 40px}header{background:var(--c);border-bottom:1px solid var(--l)}
header .w{padding:12px 16px;display:flex;gap:14px;flex-wrap:wrap}header a{color:var(--t);text-decoration:none}
a{color:var(--a)}h1{font-size:1.5rem;line-height:1.25}.card{background:var(--c);border:1px solid var(--l);border-radius:12px;padding:14px;margin:12px 0}
.mu{color:var(--m);font-size:14px}input{width:100%;padding:11px;border:1px solid var(--l);border-radius:8px;background:var(--bg);color:var(--t);font:inherit}
table{width:100%;border-collapse:collapse}td,th{padding:7px;border-bottom:1px solid var(--l);text-align:left}td:first-child{width:70px;color:var(--m)}
.tabs a{display:inline-block;padding:5px 12px;border:1px solid var(--l);border-radius:99px;margin:2px;text-decoration:none}
.ad{min-height:0}"""


def head(title, desc, path=""):
    ga = f'<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token":"{CFG["cf_beacon"]}"}}\'></script>' if CFG["cf_beacon"] else ""
    ads = f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={CFG["adsense_client"]}" crossorigin="anonymous"></script>' if CFG["adsense_client"] else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{E(title)}</title><meta name="description" content="{E(desc)}">'
            f'<link rel="canonical" href="{CFG["site_url"]}/{path}"><style>{CSS}</style>{ga}{ads}</head><body>'
            f'<header><div class="w"><b><a href="/">🎓 {E(CFG["site_name"])}</a></b><a href="/#upcoming">Upcoming</a><a href="/#latest">Results</a><a href="/about/">About</a></div></header><div class="w">')


FOOT = f'<p class="mu">Independent site, not affiliated with PRC. Source: Professional Regulation Commission (prc.gov.ph). Always verify at online.prc.gov.ph. Name corrections/removal: {E(CFG["contact_email"])}.</p></div></body></html>'


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
    SITE.mkdir()
    exams = sorted((json.loads(p.read_text()) for p in (ROOT / "data").glob("*.json") if p.stem not in ("state", "releases")),
                   key=lambda d: d["meta"]["updated"], reverse=True)
    state_f = ROOT / "data" / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"upcoming": []}
    urls = ["/"]
    for d in exams:
        m, rows = d["meta"], d["passers"]
        title = f'{m["exam"]} Results: {m["month"]} {m["year"]} List of Passers'
        shutil.copy(ROOT / "data" / f'{m["slug"]}.json', SITE / "data" / f'{m["slug"]}.json') if (SITE / "data").exists() else (
            (SITE / "data").mkdir(), shutil.copy(ROOT / "data" / f'{m["slug"]}.json', SITE / "data" / f'{m["slug"]}.json'))
        gs = groups(rows)
        for key, lab, part in gs:
            rel = f'{m["slug"]}/' + ("" if key == "all" else f"{key}/")
            tabs = "" if key == "all" else '<div class="tabs">' + "".join(
                f'<a href="/{m["slug"]}/{k}/">{l}</a>' for k, l, _ in gs) + "</div>"
            trs = "".join(f"<tr><td>{n}</td><td>{E(nm)}</td></tr>" for n, nm in part)
            stat = f'{m["passed"]:,} of {m["examinees"]:,} passed. ' if m.get("passed") and m.get("examinees") else ""
            body = (head(title + (f" ({lab})" if lab else ""), f'Official list of passers: {m["exam"]}, {m["month"]} {m["year"]}.', rel) +
                    f'<h1>{E(title)}</h1><p class="mu">{stat}Updated {m["updated"]} · <a href="{E(m["source"])}" rel="nofollow">Official PRC announcement</a></p>'
                    f'<div class="ad" id="ad-top"></div>{tabs}'
                    f'<div class="card"><input id="q" placeholder="Search name…" autocomplete="off"><p class="mu" id="c"></p></div>'
                    f'<div class="card"><table><thead><tr><th>#</th><th>Name</th></tr></thead><tbody id="tb">{trs}</tbody></table></div>'
                    f'<script>var q=document.getElementById("q"),tb=document.getElementById("tb"),c=document.getElementById("c"),orig=tb.innerHTML,all=null;'
                    f'q.addEventListener("input",async function(){{var s=q.value.trim().toUpperCase();if(!s){{tb.innerHTML=orig;c.textContent="";return}}'
                    f'if(!all)all=(await (await fetch("/data/{m["slug"]}.json")).json()).passers;'
                    f'var r=all.filter(function(x){{return x[1].indexOf(s)>-1}}).slice(0,300);c.textContent=r.length+" match(es)";'
                    f'tb.innerHTML=r.map(function(x){{return"<tr><td>"+x[0]+"</td><td>"+x[1]+"</td></tr>"}}).join("")}});</script>' + FOOT)
            write(rel + "index.html", body)
            urls.append("/" + rel)
    up = "".join(f'<div class="card"><b>{E(u["exam"])} – {u["month"]} {u["year"]}</b><br><span class="mu">Results usually post within days of the last exam day. This page updates automatically.</span></div>'
                 for u in state.get("upcoming", [])) or '<p class="mu">No upcoming release detected right now.</p>'
    lt = "".join(f'<div class="card"><a href="/{d["meta"]["slug"]}/"><b>{E(d["meta"]["exam"])} Results: {d["meta"]["month"]} {d["meta"]["year"]}</b></a>'
                 f'<br><span class="mu">{d["meta"]["count"]:,} passers · {d["meta"]["updated"]}</span></div>' for d in exams) or '<p class="mu">Waiting for the next official release…</p>'
    write("index.html", head(f'{CFG["site_name"]} – Board Exam Results', "List of passers, auto-updated from official PRC releases.") +
          f'<h1>Board Exam Results, auto-updated</h1><h2 id="upcoming">Upcoming release</h2>{up}<h2 id="latest">Latest results</h2>{lt}' + FOOT)
    write("about/index.html", head("About", "About this site", "about/") +
          f'<h1>About · Disclaimer · Privacy</h1><p>This site republishes publicly released lists of successful examinees from the PRC, automatically. It is not affiliated with PRC.</p>'
          f'<p>Privacy: we use cookie-free/standard analytics to count visits and, if enabled, Google AdSense, which may use cookies. Contact: {E(CFG["contact_email"])}</p>' + FOOT)
    write("robots.txt", f'User-agent: *\nAllow: /\nSitemap: {CFG["site_url"]}/sitemap.xml\n')
    write("sitemap.xml", '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
          "".join(f'<url><loc>{CFG["site_url"]}{u}</loc></url>' for u in urls) + "</urlset>")
    rel = ROOT / "data" / "releases.json"
    if rel.exists():
        (SITE / "data").mkdir(exist_ok=True); shutil.copy(rel, SITE / "data" / "releases.json")
    print("built", len(urls), "pages")


if __name__ == "__main__":
    main()
