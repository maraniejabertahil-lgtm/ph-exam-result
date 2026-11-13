"""Upcoming Release page (/upcoming/) and the Home redirect.
Shows the countdown ring only while a release is 4 days away and not yet published.
Otherwise it shows the list of expected releases. Live status comes from the Watcher Worker."""
import json

WATCHER_STATUS_URL = "https://ph-exam-result-watcher.maranie-jaber-tahil.workers.dev/api/upcoming-status"   # replace with your Worker URL

WINDOW_JS = """
function windowMode(ST){
  var DAY=86400000, now=Date.now(), list=(ST&&ST.upcoming)||[], i, r, pub, x, exp;
  for(i=0;i<list.length;i++){
    r=list[i];
    if(r.published_at){ pub=Date.parse(r.published_at); if(!isNaN(pub) && now<=pub+2*DAY) return {m:"fresh",u:r}; }
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
function expectedList(){
  var box=document.getElementById("list");
  box.replaceChildren();
  var items=(ST.upcoming||[]).filter(function(x){return !x.published_at});
  if(!items.length){
    var p=document.createElement("p"); p.className="mu";
    p.textContent="No upcoming release detected right now.";
    box.appendChild(p); return;
  }
  items.forEach(function(u){
    var card=document.createElement("div"); card.className="card";
    var b=document.createElement("b"); b.textContent=u.exam+" – "+u.month+" "+u.year;
    var s=document.createElement("p"); s.className="mu";
    s.textContent="Expected release: "+(u.release_text||u.release_date);
    card.append(b,s); box.appendChild(card);
  });
}
function show(){
  var wait=MODE.m==="wait";
  document.getElementById("wait").hidden=!wait;
  document.getElementById("list").hidden=wait;
  if(!wait) expectedList();
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
    from datetime import datetime, timezone
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
    """index_js and exams_json are accepted so build.py keeps working. This page has no dropdown."""
    st = json.dumps(status, ensure_ascii=False).replace("</", "<\\/")
    ring = ('<div class="ringwrap"><svg viewBox="0 0 200 200" aria-hidden="true">'
            '<circle class="trk" cx="100" cy="100" r="88"/>'
            '<circle id="arc" class="arc" cx="100" cy="100" r="88"/></svg>'
            '<div class="pct"><b id="pct">0%</b>'
            '<span class="prep">Preparing<i>.</i><i>.</i><i>.</i></span></div></div>')
    body = ('<h1>Upcoming Release</h1>'
            f'<section id="wait" hidden>{ring}</section>'
            '<section id="list" hidden></section>')
    return (head("Upcoming Release – PH Exam Result",
                 "Expected PRC release dates and the countdown to each release.", "upcoming/")
            + f'<style>{RING_CSS}</style>' + body
            + '<script>\n'
            + f'const ST = {st};\n'
            + f'const STATUS_URL = {json.dumps(WATCHER_STATUS_URL)};\n'
            + WINDOW_JS
            + 'let MODE = windowMode(ST);\n'
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
