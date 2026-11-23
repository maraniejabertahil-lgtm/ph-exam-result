"""Results-expected Facebook post.

When a board exam is within POST_DAYS (default 3) of its PRC target release date, this makes ONE Facebook post:

    𝑨𝑩𝑬𝑳𝑬 𝑹𝑬𝑺𝑼𝑳𝑻𝑺 𝟐𝟎𝟐𝟔
    The November 2026 Agricultural and Biosystems Engineers Licensure Exam (ABELE) results are expected early next week.

with a big headline picture underneath. The picture is not uploaded to Facebook: the post carries a LINK, and
Facebook builds the preview card from the page that link opens (its og:image, og:title and og:description).
So for every post this script makes a small page + a 1200x630 headline card (drawn by card.py), saved in cards/<slug>/.
copy_scans.py puts them on the site at /expected/<slug>/ before every deploy, so the link keeps working.
A person who taps the link is sent straight on to the countdown ring at /upcoming/.

Commands (used by .github/workflows/expected-post.yml):
  prepare   read the Worker's schedule, make the card + page for every exam that is due, record it as "pending"
  post      send every "pending" post to the Make webhook (FB_WEBHOOK_URL), record it as "posted"

The schedule comes from the Cloudflare Worker (/api/upcoming-status), never from PRC.

Testing without posting anything: set TEST_EXAM (and TEST_RELEASE_DATE, e.g. 2026-11-24). The card and page are made
in cards/ and the Facebook text is printed. Nothing is recorded and nothing is posted.
"""
import html as htmllib
import json, os, re, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from card import make_card_lines
from common import out, tg

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
LOG = CARDS / "posts.json"
DATA = ROOT / "data"
CFG = json.loads((ROOT / "config.json").read_text())
MANILA = timezone(timedelta(hours=8))
WATCHER = (os.environ.get("WATCHER_URL") or CFG.get("watcher_url")
           or "https://ph-exam-result-watcher.maranie-jaber-tahil.workers.dev").rstrip("/")
SITE = CFG["site_url"].rstrip("/")
POST_DAYS = int(CFG.get("expected_post_days", 3))      # EDIT HERE: post this many days before PRC's target release date
POST_FROM_HOUR, POST_TO_HOUR = 6, 22                    # Manila time: nothing is posted in the middle of the night
MAX_TRIES = 5                                           # a post the webhook keeps refusing is dropped after this many tries

# =============================================================================================
#  SHORT NAMES  <<<  EDIT HERE  >>>
#  Profession (small letters, exactly as PRC writes it in its schedule, without "Licensure Examination")  ->  short name.
#  An exam that is NOT in this list is still posted, using its full name instead of a short name
#  (for example "DENTISTS RESULTS 2026"), so a missing entry never causes a wrong post.
#  To add one, either add a line here, or add it to config.json under "exam_short_names" (same format).
# =============================================================================================
SHORT_NAMES = {
    "agricultural and biosystems engineers": "ABELE",
    "chemical engineers": "ChELE",
    "civil engineers": "CELE",
    "mechanical engineers": "MELE",
    "criminologists": "CLE",
    "nurses": "PNLE",
    "certified public accountants": "CPALE",
    "teachers": "LET",
}
SHORT_NAMES.update({k.lower(): v for k, v in (CFG.get("exam_short_names") or {}).items()})


# ---------------------------------------------------------------- text helpers
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower().replace("&", " and ")).strip()


def split_exam(raw):
    """'Chemical Engineers (CBLE)' -> ('Chemical Engineers', True, '').  'Dentists (Written)' -> ('Dentists', False, 'Written')."""
    name = re.sub(r"\s+", " ", raw or "").strip()
    computer_based = bool(re.search(r"computer[- ]based|\bCBLE\b", name, re.I))
    extra = [p.strip() for p in re.findall(r"\(([^)]*)\)", name) if not re.fullmatch(r"\s*CBLE\s*", p, re.I)]
    name = re.sub(r"\([^)]*\)", " ", name)
    name = re.sub(r"computer[- ]based", " ", name, flags=re.I)
    name = re.sub(r"licen[sc]ure\s+exam(?:ination)?s?", " ", name, flags=re.I)
    name = re.sub(r"^\s*for\s+", "", re.sub(r"\s+", " ", name).strip(), flags=re.I)
    return name.strip(" -,"), computer_based, ", ".join(extra)


def fancy(text):
    """Capital letters and digits in Facebook's bold-italic look (they are special characters, so it works in any post)."""
    res = []
    for ch in text:
        if "A" <= ch <= "Z":
            res.append(chr(0x1D468 + ord(ch) - 65))
        elif "a" <= ch <= "z":
            res.append(chr(0x1D482 + ord(ch) - 97))
        elif "0" <= ch <= "9":
            res.append(chr(0x1D7CE + ord(ch) - 48))
        else:
            res.append(ch)
    return "".join(res)


def expected_phrase(release_iso, today):
    """'expected tomorrow' / 'expected this Thursday' / 'expected early next week' / 'expected on December 8'."""
    d = date.fromisoformat(release_iso)
    days = (d - today).days
    if days <= 0:
        return "expected today"
    if days == 1:
        return "expected tomorrow"
    weeks = ((d - timedelta(days=d.weekday())) - (today - timedelta(days=today.weekday()))).days // 7
    if weeks == 0:
        return f"expected this {d.strftime('%A')}"
    if weeks == 1:
        if d.weekday() <= 1:
            return "expected early next week"
        if d.weekday() <= 3:
            return "expected in the middle of next week"
        return "expected late next week"
    return f"expected on {d.strftime('%B')} {d.day}"


def describe(item, today, moved=False):
    """Everything the post, the card and the page need, worked out from one schedule item."""
    profession, computer_based, extra = split_exam(item.get("exam", ""))
    short = SHORT_NAMES.get(profession.lower(), "")
    month = (item.get("exam_month") or item.get("month") or "").strip()
    year = str(item.get("exam_year") or item.get("year") or "").strip()
    month_from_release = not item.get("exam_month")
    if not month or not year:                              # the Worker always sends one of the two; this is only a safety net
        rel = date.fromisoformat(item["release_date"])
        month, year, month_from_release = rel.strftime("%B"), str(rel.year), True
    display = f"{profession} {'Computer-Based ' if computer_based else ''}Licensure Exam" + (f" ({extra})" if extra else "")
    headline = f"{short or profession.upper()} RESULTS"
    when = expected_phrase(item["release_date"], today)
    sentence = f"The {month} {year} {display}{f' ({short})' if short else ''} results are {'now ' if moved else ''}{when}."
    message = f"{fancy(headline + ' ' + year)}\n{sentence}"
    subtitle = f"{month} {year} {display}".upper()
    title = f"{headline}: {month} {year} {display} - Countdown to the List of Passers"
    return dict(profession=profession, short=short, month=month, year=year, month_from_release=month_from_release,
                display=display, headline=headline, subtitle=subtitle, title=title, when=when, message=message,
                release_date=item["release_date"], computer_based=computer_based)


# ---------------------------------------------------------------- the headline card (1200 x 630)
def make_card(info, path):
    """The approved headline picture (see card.py): big headline, month + year + exam name, your site address."""
    make_card_lines(info["headline"], info["subtitle"], path,
                    site=SITE.replace("https://", "").replace("http://", ""), brand=CFG.get("site_name", "PH EXAM RESULT"))


# ---------------------------------------------------------------- the page the Facebook link opens
def make_page(info, slug, path):
    """Facebook reads the picture, title and description from this page's tags (it does not run scripts).
    A person who taps the link has scripts, so the page sends them straight on to the countdown ring (/upcoming/).
    The small body is only a fallback for the rare browser with scripts turned off."""
    url = f"{SITE}/expected/{slug}/"
    img = f"{url}card.png"
    when = datetime.strptime(info["release_date"], "%Y-%m-%d").strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc = f"Expected release: {when}. Watch the countdown here; the official list of passers is posted as soon as PRC releases it."
    e = htmllib.escape
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(info['title'])}</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="noindex,follow">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(CFG.get('site_name', 'PH EXAM RESULT'))}">
<meta property="og:title" content="{e(info['title'])}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(img)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<script>location.replace("/upcoming/");</script>
<style>
body{{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6fa;color:#1f2a3c}}
main{{max-width:720px;margin:0 auto;padding:28px 16px 40px;text-align:center}}
a.btn{{display:inline-block;margin-top:14px;padding:12px 22px;border-radius:999px;background:#2f6fe0;color:#fff;text-decoration:none;font-weight:600}}
</style></head><body><main>
<h1>{e(info['headline'])}</h1>
<p>{e(desc)}</p>
<a class="btn" href="/upcoming/">Open the countdown</a>
</main></body></html>
""")


# ---------------------------------------------------------------- the record of what was made / posted
def load_log():
    try:
        data = json.loads(LOG.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_log(log):
    CARDS.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1))


def released_already(info):
    """True if this exam's result for the same month and year is already on the site (a stale schedule must not cause a post)."""
    me = norm(info["profession"])
    for p in DATA.glob("*.json"):
        if p.stem in ("state", "releases"):
            continue
        try:
            meta = json.loads(p.read_text())["meta"]
            theirs = norm(meta.get("exam", ""))
            same_month = norm(meta.get("month", "")).startswith(norm(info["month"])[:3]) and str(meta.get("year")) == info["year"]
        except Exception:
            continue
        if same_month and me and (me in theirs or theirs in me):
            return True
    return False


def fetch_items():
    r = requests.get(f"{WATCHER}/api/upcoming-status", timeout=20, headers={"User-Agent": "ph-exam-result-expected-post"})
    r.raise_for_status()
    return [x for x in (r.json().get("upcoming") or []) if x.get("release_date") and not x.get("published_at")]


def test_items():
    rel = os.environ.get("TEST_RELEASE_DATE") or (datetime.now(MANILA).date() + timedelta(days=2)).isoformat()
    it = {"exam": os.environ["TEST_EXAM"], "release_date": rel}
    if os.environ.get("TEST_MONTH"):
        it["exam_month"] = os.environ["TEST_MONTH"]
        it["exam_year"] = os.environ.get("TEST_YEAR") or rel[:4]
    else:
        d = date.fromisoformat(rel)
        it["month"], it["year"] = d.strftime("%B"), str(d.year)
    return [it]


def cmd_prepare():
    now = datetime.now(MANILA)
    today = now.date()
    test = bool(os.environ.get("TEST_EXAM"))
    if not test and not (POST_FROM_HOUR <= now.hour < POST_TO_HOUR):
        print(f"{now:%H:%M} Manila time: outside posting hours ({POST_FROM_HOUR}:00-{POST_TO_HOUR}:00), nothing to do")
        out(todo=0)
        return
    items = test_items() if test else fetch_items()
    print(f"{len(items)} upcoming exam(s) from the Worker")
    log = [] if test else load_log()
    changed = False
    for it in items:
        try:
            days = (date.fromisoformat(it["release_date"]) - today).days
        except ValueError:
            continue
        if not test and not (0 <= days <= POST_DAYS):
            continue
        profession, cbt, extra = split_exam(it.get("exam", ""))
        exam_key = norm(f"{profession} {'cbt' if cbt else ''} {extra}")
        key = f"{exam_key}|{it['release_date']}"
        if any(e["key"] == key for e in log):
            continue
        earlier = [e for e in log if e["exam_key"] == exam_key and e["release_date"] != it["release_date"]
                   and (today - date.fromisoformat(e["created"])).days <= 30]
        info = describe(it, today, moved=bool(earlier))
        if not test and released_already(info):
            print(f"skip {it['exam']}: its results are already on the site")
            continue
        slug = slugify(f"{info['short'] or info['profession']}-{info['month']}-{info['year']}-expected-{it['release_date']}")
        make_card(info, CARDS / slug / "card.png")
        make_page(info, slug, CARDS / slug / "index.html")
        link = f"{SITE}/expected/{slug}/"
        print("=" * 60, f"\n{it['exam']}  (release {it['release_date']}, in {days} day(s))")
        if info["month_from_release"]:
            print("NOTE: the Worker sent no exam month, so the RELEASE month is used in the text.")
        print(f"link: {link}\n--- Facebook text ---\n{info['message']}\n---------------------")
        log.append(dict(key=key, exam_key=exam_key, exam=it["exam"], release_date=it["release_date"], slug=slug,
                        created=today.isoformat(), status="pending", tries=0, message=info["message"], link=link))
        changed = True
    if changed and not test:
        save_log(log)
    pending = 0 if test else sum(1 for e in log if e["status"] == "pending")
    print(f"pending posts: {pending}")
    out(todo=pending)


def notify(text):
    if os.environ.get("DRY_RUN") == "true":
        print("[telegram skipped: dry run]", text)
    else:
        tg(text)


def cmd_post():
    if os.environ.get("TEST_EXAM"):
        print("test mode: nothing is posted")
        return
    hook = os.environ.get("FB_WEBHOOK_URL")
    log = load_log()
    for e in log:
        if e["status"] != "pending":
            continue
        e["tries"] = e.get("tries", 0) + 1
        try:
            if not hook:
                raise RuntimeError("FB_WEBHOOK_URL is not set")
            r = requests.post(hook, json={"message": e["message"], "link": e["link"]}, timeout=20)
            ok, why = r.ok, f"HTTP {r.status_code} {r.text[:120]}"
        except Exception as ex:
            ok, why = False, str(ex)[:150]
        if ok:
            e["status"] = "posted"
            e["posted_at"] = datetime.now(MANILA).isoformat(timespec="seconds")
            print(f"posted: {e['exam']} ({e['release_date']})")
            notify(f"📣 Facebook post sent: results expected for {e['exam']} ({e['release_date']})\n{e['link']}")
        else:
            print(f"post failed ({e['tries']}/{MAX_TRIES}): {e['exam']}: {why}")
            if e["tries"] >= MAX_TRIES:
                e["status"] = "failed"
                notify(f"⚠️ Facebook 'results expected' post for {e['exam']} failed {MAX_TRIES} times and was dropped: {why}")
        save_log(log)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        cmd_prepare()
    elif cmd == "post":
        cmd_post()
    else:
        sys.exit(f"unknown command: {cmd!r} (use prepare or post)")
