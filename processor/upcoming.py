"""Upcoming Release page (/upcoming/), status.json, and the Home default redirect.

Modes, decided in the browser from status.json and the visitor's clock (Philippine time):
  wait  : 4 days before expected release until publication. Ring 0% -> 99%, content blank.
  fresh : 2 days after publication. Ring gone, only that release (no dropdown).
  other : results with dropdown, newest selected by default.
"""
import json
from datetime import datetime, timezone

SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

WINDOW_JS = """
function windowMode(ST){
  var DAY = 86400000, now = Date.now();
  var u = ST && ST.upcoming && ST.upcoming[0];
  if(!u) return {m:"other"};
  var exp = Date.parse(u.release_date + "T00:00:00+08:00");
  var pub = u.published_at ? Date.parse(u.published_at) : null;
  if(pub === null){
    if(!isNaN(exp) && now >= exp - 4*DAY) return {m:"wait", u:u, exp:exp, start:exp - 4*DAY};
    return {m:"other", u:u};
  }
  if(now <= pub + 2*DAY) return {m:"fresh", u:u, slug:u.slug};
  return {m:"other", u:u};
}
"""

RING_CSS = """
#wait{text-align:center;padding:12px 0 40px}
.ringwrap{position:relative;width:min(260px,70vw);margin:28px auto 12px}
.ringwrap svg{width:100%;height:auto;display:block}
.trk{fill:none;stroke:#eaf1ff;stroke-width:12}
.arc{fill:none;stroke:#4a7fe8;stroke-width:12;stroke-linecap:round;transform:rotate(-90deg);transform-origin:100px 100px;transition:stroke-dashoffset .9s linear}
.pct{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.pct b{font-size:3rem;color:var(--text);line-height:1.1}
.prep{color:var(--mu);font-size:1rem}
.prep i{display:inline-block;font-style:normal;animation:bob 1.2s infinite ease-in-out}
.prep i:nth-child(2){animation-delay:.15s}
.prep i:nth-child(3){animation-delay:.3s}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@media (prefers-reduced-motion:reduce){.prep i{animation:none}}
"""

UPCOMING_JS = """
var ARC = document.getElementById("arc"), C = 2*Math.PI*88;
ARC.style.strokeDasharray = C;
function ringSet(p){
  ARC.style.strokeDashoffset = C*(1-p/100);
  document.getElementById("pct").textContent = Math.floor(p) + "%";
}
function tick(){
  if(MODE.m !== "wait") return;
  var f = Math.min(1, Math.max(0, (Date.now() - MODE.start) / (MODE.exp - MODE.start)));
  ringSet(f * 99);
}
function show(){
  var wait = MODE.m === "wait";
  document.getElementById("wait").hidden = !wait;
  document.getElementById("res").hidden = wait;
  var u = ST.upcoming && ST.upcoming[0];
  var info = document.getElementById("info");
  if(!wait && u && !u.published_at){
    var card = document.createElement("div"); card.className = "card";
    var b = document.createElement("b"); b.textContent = u.exam + " – " + u.month + " " + u.year;
    var s = document.createElement("p"); s.className = "mu";
    s.textContent = "Expected release: " + (u.release_text || u.release_date);
    card.append(b, s); info.replaceChildren(card);
  } else { info.replaceChildren(); }
  if(MODE.m === "fresh") document.getElementById("exsel").hidden = true;
}
async function poll(){
  var s;
  try { s = await (await fetch("/status.json", {cache: "no-store"})).json(); } catch(e) { return; }
  ST.upcoming = s.upcoming || [];
  var next = windowMode(ST);
  if(next.m === MODE.m && next.slug === MODE.slug) return;
  if(MODE.m === "wait"){ ringSet(100); setTimeout(function(){ location.reload(); }, 2500); }
  else { location.reload(); }
}
show(); tick();
setInterval(tick, 1000);
setInterval(poll, 60000);
"""


def build_status(state, exams):
    """Writes /status.json: each upcoming release, and the time its result was published (if it has been)."""
    by_slug = {d["meta"].get("slug"): d["meta"] for d in exams}
    items = []
    for u in state.get("upcoming", []):
        slug = u.get("slug", "")
        match = by_slug.get(slug)
        pub = u.get("published_at")
        if match and not pub:
            try:
                t = datetime.strptime(match["updated"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                pub = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (KeyError, ValueError):
                pub = None
        items.append({
            "exam": u.get("exam", ""), "month": u.get("month", ""), "year": str(u.get("year", "")),
            "release_date": u.get("release_date") or "",
            "release_text": u.get("release_date_text") or u.get("release_within") or "",
            "published_at": pub, "slug": slug,
        })
    return {"upcoming": items}


def upcoming_page(head, FOOT, index_js, exams_json, status):
    st = json.dumps(status, ensure_ascii=False).replace("</", "<\\/")
    ring = ('<div class="ringwrap"><svg viewBox="0 0 200 200" aria-hidden="true">'
            '<circle class="trk" cx="100" cy="100" r="88"/>'
            '<circle id="arc" class="arc" cx="100" cy="100" r="88"/></svg>'
            '<div class="pct"><b id="pct">0%</b>'
            '<span class="prep">Preparing<i>.</i><i>.</i><i>.</i></span></div></div>')
    bar = ('<div class="bar"><nav class="letters" id="letters" aria-label="Choose a letter"></nav>'
           f'<button class="sbtn" id="sb" type="button" aria-label="Search passer name" aria-expanded="false">{SEARCH_SVG}</button></div>'
           '<div class="sbox" id="sbox" hidden><input id="q" type="search" placeholder="Type a passer\'s first name…" autocomplete="off"></div>')
    res = ('<section id="res"><h1>Upcoming Release</h1>' + bar +
           '<section class="card"><select id="exsel" class="exsel" aria-label="Choose examination"></select>'
           '<h2 id="hd">Letter A</h2><p class="mu" id="cnt"></p>'
           '<ul class="names" id="names"></ul><p class="empty" id="none" hidden></p></section></section>')
    return (head("Upcoming Release – PH Exam Result",
                 "Upcoming PRC and CSC release status, and the latest results.", "upcoming/")
            + f'<style>{RING_CSS}</style>'
            + f'<section id="wait" hidden>{ring}</section>'
            + '<section id="info"></section>' + res
            + '<script>\n'
            + f'const ST = {st};\n'
            + f'const ALL = {exams_json};\n'
            + WINDOW_JS
            + 'const MODE = windowMode(ST);\n'
            + 'const EXAMS = MODE.m === "fresh" ? ALL.filter(e => e.slug === MODE.slug) : ALL;\n'
            + index_js
            + UPCOMING_JS
            + '</script>'
            + FOOT)


def home_redirect_script():
    """Added to the Home page. During the waiting period or the 2 days after publication, '/' opens Upcoming Release."""
    return ("<script>" + WINDOW_JS +
            "(async function(){"
            "if(location.search.indexOf('home')>-1)return;"
            "try{var s=await (await fetch('/status.json',{cache:'no-store'})).json();"
            "var m=windowMode(s).m;"
            "if(m==='wait'||m==='fresh')location.replace('/upcoming/');}catch(e){}"
            "})();</script>")
