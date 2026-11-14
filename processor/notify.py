"""After the site is deployed: Telegram + Make webhook (Facebook Page post), then record the release for the owner dashboard.
Runs only in the publish job, which holds the 'site' lock, so the release log is never written by two runs at once."""
import json, os, time
from pathlib import Path
import requests
ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
slug = os.environ.get("SLUG", "").strip()
if not slug: raise SystemExit(0)                      # schedule notices and skipped articles have no list to announce
src = ROOT / "data" / f"{slug}.json"
if not src.exists(): raise SystemExit(0)
m = json.loads(src.read_text())["meta"]
live = int(time.time() * 1000)
secs = round((live - int(m.get("detected_at") or live)) / 1000)
link = f'{CFG["site_url"]}/{slug}/'
nm = f'{m["exam"]} ({m["month"]} {m["year"]})'
tgs = fbs = "off"
t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if t and c:
    r = requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": f'✅ PUBLISHED: {nm}\n{m["count"]:,} passers · live {secs}s after detection ({m["method"]})\n{link}'}, timeout=20)
    tgs = "ok" if r.ok else f"fail {r.status_code}"
hook = os.environ.get("FB_WEBHOOK_URL")
if hook:
    msg = f'🎓 {m["exam"]} RESULTS ({m["month"]} {m["year"]}) are OUT!\n' + (f'{m["passed"]:,} passed. ' if m.get("passed") else "") + "Check the official list of passers here 👇"
    r = requests.post(hook, json={"message": msg, "link": link}, timeout=20)
    fbs = "ok" if r.ok else f"fail {r.status_code}"
    if not r.ok and t and c: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": f"⚠️ Facebook post failed for {nm}: {r.text[:150]}"}, timeout=20)
rel_f = ROOT / "data" / "releases.json"
rel = json.loads(rel_f.read_text()) if rel_f.exists() else []
rel = [x for x in rel if x.get("slug") != slug]          # one row per list, even if the job re-runs
rel.insert(0, dict(slug=slug, exam=m["exam"], month=m["month"], year=m["year"], count=m["count"], live_secs=secs, method=m["method"], tg=tgs, fb=fbs, at=live))
rel_f.write_text(json.dumps(rel[:100]))
print(f"published {slug}: tg={tgs} fb={fbs} live_secs={secs}")