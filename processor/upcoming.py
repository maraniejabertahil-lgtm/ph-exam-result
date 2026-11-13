"""Upcoming Release page (/upcoming/) and the Home redirect.
Live status comes from the Watcher Worker at /api/upcoming-status (written by reportReleased()
and reconcileSchedule() in worker/index.js). status.json from the last build is only a fallback."""
import json
from datetime import datetime, timezone

WATCHER_STATUS_URL = "https://ph-exam-result-watcher.maranie-jaber-tahil.workers.dev/api/upcoming-status"   # replace with your Worker URL

SEARCH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

WINDOW_JS = """
function windowMode(ST){
  var DAY=86400000, now=Date.now(), list=(ST&&ST.upcoming)||[], i, r, pub, x, exp;
  for(i=0;i<list.length;i++){
    r=list[i];
    if(r.published_at){ pub=Date.parse(r.published_at); if(!isNaN(pub) && now<=pub+2*DAY) return {m:"fresh",u:r,slug:r.slug}; }
  }
  for(i=0;i<list.length;i++){
    x=list[i];
    if(x.published_at) continue;
    exp=Date.parse(x.release_date+"T00:00:00+08:00");
    if(!isNaN(exp) && now>=exp-4*DAY) return {m:"wait",u:x,exp:exp,start:exp-4*DAY};
  }
  return {m:"other"};
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
var ARC=document.getElementById("arc"), C=2*Math.PI*88;
ARC.style.strokeDasharray=C;
function ringSet(p){ ARC.style.strokeDashoffset=C*(1-p/100); document.getElementById("pct").textContent=Math.floor(p)+"%"; }
function tick(){
  if(MODE.m!=="wait") return;
  var f=Math.min(1,Math.max(0,(Date.now()-MODE.start)/(MODE.exp-MODE.start)));
  ringSet(f*99);
}
function show(){
  var wait=MODE.m==="wait";
  document.getElementById("wait").hidden=!wait;
  document.getElementById("res").hidden=wait;
  document.getElementById("exsel").hidden=MODE.m==="fresh";
  var info=document.getElementById("info");
  info.replaceChildren();
  var u=(ST.upcoming||[]).filter(function(x){return !x.published_at})[0];
  if(MODE.m==="other" && u){
    var card=document.createElement("div"); card.className="card";
    var b=document.createElement("b"); b.textContent=u.exam+" – "+u.month+" "+u.year;
    var s=document.createElement("p"); s.className="mu";
    s.textContent="Expected release: "+(u.release_text||u.release_date);
    card.append(b,s); info.replaceChildren(card);
  }
}
async function poll(){
  var s;
  try { s=await (await fetch(STATUS_URL,{cache:"no-store"})).json(); } catch(e){ return; }
  ST.upcoming=s.upcoming||[];
  var prev=MODE.m;
  MODE=windowMode(ST);
  if(prev==="wait" && MODE.m!=="wait"){ ringSet(100); setTimeout(show,1500); }
  else { show(); }
  tick();
}
show(); tick(); poll();
setInterval(tick,1000);
setInterval(poll,60000);
"""


def build_status(state, exams):
    """Fallback /status.json written at build time. The live version comes from the Worker."""
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
            + f'const EXAMS = {exams_json};\n'
            + f'const STATUS_URL = {json.dumps(WATCHER_STATUS_URL)};\n'
            + WINDOW_JS
            + 'let MODE = windowMode(ST);\n'
            + index_js
            + UPCOMING_JS
            + '</script>'
            + FOOT)


def home_redirect_script():
    """Added to the Home page. During the waiting period or the 2 days after publication, '/' opens Upcoming Release."""
    return ("<script>" + WINDOW_JS +
            "(async function(){"
            "if(location.search.indexOf('home')>-1)return;"
            "try{var s=await (await fetch(" + json.dumps(WATCHER_STATUS_URL) + ",{cache:'no-store'})).json();"
            "var m=windowMode(s).m;"
            "if(m==='wait'||m==='fresh')location.replace('/upcoming/');}catch(e){}"
            "})();</script>")
