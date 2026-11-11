import json, re, subprocess, sys
from collections import Counter
from common import *

MAX_UNREADABLE = lambda passed: max(10, passed // 1000)   # up to this many gaps are published as marked placeholders


def surname(name):
    return name.split(",")[0]


def sort_key(name, nospace):
    s = surname(name).upper()
    return re.sub(r"[^A-ZÑ]", "", s) if nospace else re.sub(r"\s+", " ", s).strip()


def main():
    job = json.loads((WORK / "job.json").read_text())
    state_f = DATA / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"upcoming": []}
    if job["kind"] == "schedule":
        if not (DATA / f"{job['slug']}.json").exists() and job["slug"] not in [u["slug"] for u in state["upcoming"]]:
            state["upcoming"].append({k: job[k] for k in ("slug", "exam", "month", "year", "title", "url")})
            state_f.write_text(json.dumps(state, indent=1)); print("upcoming added", job["slug"])
        return
    exact = WORK / "exact.json"
    how = "text" if exact.exists() else "screenshot"
    files = [exact] if exact.exists() else sorted(WORK.glob("reads_*.json"))
    passed = job.get("passed") or 0
    cand = {}
    for f in files:
        for r in json.loads(f.read_text()):
            for k, v in r.items():
                cand.setdefault(int(k), Counter())[v] += 1
    passed = passed or max(cand, default=0)
    cand = {n: c for n, c in cand.items() if 1 <= n <= passed}      # numbers beyond the list are misreads
    # "loose" reads: numbered lines the strict reader rejected. Used ONLY to fill numbers nobody read strictly.
    loose = {}
    for f in sorted(WORK.glob("loose_*.json")):
        for r in json.loads(f.read_text()):
            for k, v in r.items():
                if 1 <= int(k) <= passed:
                    loose.setdefault(int(k), Counter())[v] += 1
    chosen, doubt, share = {}, [], {}
    for n, c in cand.items():
        name, top = c.most_common(1)[0]
        chosen[n] = name
        share[n] = top / sum(c.values())
        if how != "text" and (share[n] < 0.67 or not NAME_OK.match(name)):
            doubt.append(n)

    # The list is in alphabetical order, so a name that breaks the order is probably misread.
    # Prefer another reading of the SAME number that fits (never invent a name); otherwise just flag it.
    swapped = 0
    if how != "text" and len(chosen) > 50:
        best = None
        for nospace in (False, True):
            seq = [sort_key(chosen[n], nospace) for n in sorted(chosen)]
            ratio = sum(a <= b for a, b in zip(seq, seq[1:])) / max(1, len(seq) - 1)
            if best is None or ratio > best[0]:
                best = (ratio, nospace)
        print(f"alphabetical order check: {best[0]:.1%} of neighbours in order")
        if best[0] >= 0.97:
            nospace = best[1]
            fits = lambda name, a, b: (a is None or sort_key(a, nospace) <= sort_key(name, nospace)) and \
                                      (b is None or sort_key(name, nospace) <= sort_key(b, nospace))
            for n in sorted(chosen):
                prev, nxt = chosen.get(n - 1), chosen.get(n + 1)
                if fits(chosen[n], prev, nxt):
                    continue
                if share[n] < 0.8:
                    alt = next((a for a, _ in cand[n].most_common() if a != chosen[n] and fits(a, prev, nxt)), None)
                    if alt:
                        chosen[n] = alt; swapped += 1
                        continue
                doubt.append(n)
    filled = []
    for n in range(1, passed + 1):
        if n not in chosen and n in loose:
            chosen[n] = loose[n].most_common(1)[0][0]
            filled.append(n); doubt.append(n)
    missing = [n for n in range(1, passed + 1) if n not in chosen]
    print(f"rows {len(chosen)}/{passed}  missing {len(missing)}  doubtful {len(set(doubt))}  "
          f"order-fixed {swapped}  filled-from-loose {len(filled)} {filled[:20]}")
    if missing:
        attempt = int(os.environ.get("ATTEMPT") or 1)
        print(f"missing numbers: {missing[:40]}")
        if attempt >= 3 or len(missing) <= MAX_UNREADABLE(passed):
            # A few gaps survive even the sharper second look: publish, but clearly marked, instead of a 10 minute re-run.
            for n in missing:
                chosen[n] = "(NOT READABLE - SEE OFFICIAL LIST)"; doubt.append(n)
            tg(f"⚠️ {job['title']}: published with {len(missing)} unreadable row(s): numbers {missing[:30]}. Please fill them in from the official list.")
            missing = []
        else:
            tg(f"⚠️ {job['title']}: {len(missing)} numbers not read yet {missing[:15]}. Attempt {attempt} of 3.")
            subprocess.run(["gh", "workflow", "run", "process.yml", "-f", f"url={job['url']}",
                            "-f", f"attempt={attempt + 1}", "-f", f"detected={job['detected']}"])
            sys.exit(1)
    rows = [[n, chosen[n]] for n in range(1, passed + 1)]
    meta = dict(slug=job["slug"], exam=job["exam"], month=job["month"], year=job["year"], title=job["title"],
                source=job["url"], passed=job["passed"], examinees=job["total"], count=len(rows), method=how,
                review=sorted(set(doubt))[:100], updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    (DATA / f"{job['slug']}.json").write_text(json.dumps({"meta": meta, "passers": rows}, ensure_ascii=False, separators=(",", ":")))
    state["upcoming"] = [u for u in state["upcoming"] if u["slug"] != job["slug"]]
    state_f.write_text(json.dumps(state, indent=1))
    (DATA / "pending.json").write_text(json.dumps(dict(meta, detected_at=job["detected"], built_at=now_ms())))
    if doubt:
        d = sorted(set(doubt))
        tg(f"ℹ️ {job['title']}\nPublished all {len(rows)} names. {len(d)} look less certain (numbers {d[:30]}). Please spot-check them.")
    print("built", job["slug"], len(rows), how)


if __name__ == "__main__":
    main()
