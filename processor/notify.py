"""After the site is deployed: Telegram + Make webhook (Facebook Page post), then record the release for the owner dashboard.
Runs only in the publish job, which holds the 'site' lock, so the release log is never written by two runs at once.

PIPELINE=2 (set by complete-results.yml): pipeline 1 already published and timed this release.
Pipeline 2 must not replace that live time with its own (much later) time, so it only adds images_secs.
Pipeline 2 also never posts to Facebook: the "RESULTS are OUT" post comes from pipeline 1 only."""
import json, os, time
from pathlib import Path
import requests
ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
slug = os.environ.get("SLUG", "").strip()
if not slug: raise SystemExit(0)                      # schedule notices and skipped articles have no list to announce
src = ROOT / "data" / f"{slug}.json"
if not src.exists(): raise SystemExit(0)
second = os.environ.get("PIPELINE") == "2"
m = json.loads(src.read_text())["meta"]
live = int(time.time() * 1000)
secs = round((live - int(m.get("detected_at") or live)) / 1000)
link = f'{CFG["site_url"]}/{slug}/'
nm = f'{m["exam"]} ({m["month"]} {m["year"]})'
tgs = fbs = "off"
t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if t and c:
    text = (f'🖼 Page images added: {nm}\n{link}' if second
            else f'✅ PUBLISHED: {nm}\n{m["count"]:,} passers · live {secs}s after detection ({m["method"]})\n{link}')
    r = requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=20)
    tgs = "ok" if r.ok else f"fail {r.status_code}"
hook = os.environ.get("FB_WEBHOOK_URL")
if hook and not second:                               # Facebook: pipeline 1 only (pipeline 2 does not post anymore)
    msg = f'🎓 {m["exam"]} RESULTS ({m["month"]} {m["year"]}) are OUT!\n' + (f'{m["passed"]:,} passed. ' if m.get("passed") else "") + "Check the official list of passers here 👇"
    r = requests.post(hook, json={"message": msg, "link": link}, timeout=20)
    fbs = "ok" if r.ok else f"fail {r.status_code}"
    if not r.ok and t and c: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": f"⚠️ Facebook post failed for {nm}: {r.text[:150]}"}, timeout=20)
rel_f = ROOT / "data" / "releases.json"
rel = json.loads(rel_f.read_text()) if rel_f.exists() else []
prev = next((x for x in rel if x.get("slug") == slug), None)
if second and prev:
    prev["images_secs"] = secs                        # pipeline 2 finished this long after detection; live_secs stays pipeline 1's
    print(f"images added {slug}: images_secs={secs}; live_secs stays {prev.get('live_secs')}")
else:
    rel = [x for x in rel if x.get("slug") != slug]   # one row per list, even if the job re-runs
    rel.insert(0, dict(slug=slug, exam=m["exam"], month=m["month"], year=m["year"], count=m["count"], live_secs=secs, method=m["method"], tg=tgs, fb=fbs, at=live))
    print(f"published {slug}: tg={tgs} fb={fbs} live_secs={secs}")
rel_f.write_text(json.dumps(rel[:100]))
