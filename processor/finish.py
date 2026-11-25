import json, os, re, subprocess, sys
from collections import Counter
from common import *

MAX_UNREADABLE = lambda passed: max(10, passed // 1000)
SORT_TRANS = str.maketrans("ÑÁÉÍÓÚÜ", "NAEIOUU")


def norm_name(v):
    v = re.sub(r"\s+", " ", v).strip()
    v = re.sub(r"\s+,", ",", v)
    v = re.sub(r",\s*", ", ", v)
    return re.sub(r"^[\s.,'-]+|[\s,-]+$", "", v)


def surname(name):
    return name.split(",")[0]


def sort_key(name, nospace):
    s = surname(name).upper().translate(SORT_TRANS)
    return re.sub(r"[^A-Z]", "", s) if nospace else re.sub(r"\s+", " ", s).strip()


def nearest_neighbor(chosen, n, step, limit):
    i = n + step
    steps = 0
    while 1 <= i <= limit and steps < 5:
        if i in chosen:
            return i, chosen[i]
        i += step
        steps += 1
    return None, None


def main():
    job = json.loads((WORK / "job.json").read_text())
    state_f = DATA / "state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {"upcoming": []}
    if job["kind"] == "schedule":
        if (DATA / f"{job['slug']}.json").exists():
            return
        info = job.get("info") or {}
        entry = next((u for u in state["upcoming"] if u["slug"] == job["slug"]), None)
        fields = dict(slug=job["slug"], exam=job["exam"], month=job["month"], year=job["year"], title=job["title"], url=job["url"],
                      release_date=info.get("release_date"), release_date_text=info.get("release_date_text"),
                      release_within=info.get("release_within"), status=info.get("status") or "scheduled",
                      published_at=info.get("published_at"), note=info.get("note"), checked=now_ms())
        if entry is None:
            state["upcoming"].append(dict(fields, history=[]))
            tg(f"📅 New PRC announcement: {job['title']}\nTarget release: {fields['release_date_text'] or fields['release_within'] or 'not stated yet'}\nStatus: {fields['status']}\n{job['url']}")
        else:
            old = (entry.get("release_date"), entry.get("status"))
            if old != (fields["release_date"], fields["status"]):
                entry.setdefault("history", []).append(dict(at=now_ms(), release_date=old[0], status=old[1]))
                tg(f"🔔 PRC release update: {job['title']}\nTarget release: {old[0] or 'n/a'} -> {fields['release_date'] or 'n/a'}\nStatus: {old[1]} -> {fields['status']}\n{job['url']}")
            entry.update({k: v for k, v in fields.items() if v is not None})
        state_f.write_text(json.dumps(state, indent=1)); print("upcoming saved", job["slug"])
        return
    exact = WORK / "exact.json"
    how = "text" if exact.exists() else "screenshot"
    files = [exact] if exact.exists() else sorted(WORK.glob("reads_*.json"))
    passed = job.get("passed") or 0
    cand = {}
    for f in files:
        for r in json.loads(f.read_text()):
            for k, v in r.items():
                nv = v if how == "text" else norm_name(v)
                if nv:
                    cand.setdefault(int(k), Counter())[nv] += 1
    passed = passed or max(cand, default=0)
    cand = {n: c for n, c in cand.items() if 1 <= n <= passed}
    loose = {}
    for f in sorted(WORK.glob("loose_*.json")):
        for r in json.loads(f.read_text()):
            for k, v in r.items():
                nv = norm_name(v)
                if nv and 1 <= int(k) <= passed:
                    loose.setdefault(int(k), Counter())[nv] += 1
    chosen, doubt, share = {}, [], {}
    for n, c in cand.items():
        name, top = c.most_common(1)[0]
        chosen[n] = name
        share[n] = top / sum(c.values())
        if how != "text" and (share[n] < 0.67 or not NAME_OK.match(name)):
            doubt.append(n)

    swapped = 0
    order_ok, nospace = False, False
    fits = lambda name, a, b: True
    if how != "text" and len(chosen) > 50:
        best = None
        for ns in (False, True):
            seq = [sort_key(chosen[n], ns) for n in sorted(chosen)]
            ratio = sum(a <= b for a, b in zip(seq, seq[1:])) / max(1, len(seq) - 1)
            if best is None or ratio > best[0]:
                best = (ratio, ns)
        print(f"alphabetical order check: {best[0]:.1%} of neighbours in order")
        if best[0] >= 0.97:
            order_ok, nospace = True, best[1]
            fits = lambda name, a, b: (a is None or sort_key(a, nospace) <= sort_key(name, nospace)) and \
                                      (b is None or sort_key(name, nospace) <= sort_key(b, nospace))
            for n in sorted(chosen):
                prev_idx, prev = nearest_neighbor(chosen, n, -1, passed)
                nxt_idx, nxt = nearest_neighbor(chosen, n, 1, passed)
                if fits(chosen[n], prev, nxt):
                    continue
                if prev_idx is not None and not (sort_key(prev, nospace) <= sort_key(chosen[n], nospace)):
                    _, prev2 = nearest_neighbor(chosen, prev_idx, -1, passed)
                    if fits(chosen[n], prev2, nxt) and share.get(prev_idx, 1.0) < share[n]:
                        continue
                if nxt_idx is not None and not (sort_key(chosen[n], nospace) <= sort_key(nxt, nospace)):
                    _, nxt2 = nearest_neighbor(chosen, nxt_idx, 1, passed)
                    if fits(chosen[n], prev, nxt2) and share.get(nxt_idx, 1.0) < share[n]:
                        continue
                if share[n] < 0.8 or not NAME_OK.match(chosen[n]):
                    alt = next((a for a, _ in cand[n].most_common() if a != chosen[n] and fits(a, prev, nxt)), None)
                    if not alt and n in loose:
                        alt = next((a for a, _ in loose[n].most_common() if NAME_OK.match(a) and fits(a, prev, nxt)), None)
                    if alt:
                        chosen[n] = alt; swapped += 1
                        continue
                doubt.append(n)
    filled = []
    for n in range(1, passed + 1):
        if n not in chosen and n in loose:
            if order_ok:
                _, prev = nearest_neighbor(chosen, n, -1, passed)
                _, nxt = nearest_neighbor(chosen, n, 1, passed)
                pick = next((a for a, _ in loose[n].most_common() if fits(a, prev, nxt)), None)
                chosen[n] = pick or loose[n].most_common(1)[0][0]
            else:
                chosen[n] = loose[n].most_common(1)[0][0]
            filled.append(n); doubt.append(n)
    missing = [n for n in range(1, passed + 1) if n not in chosen]
    print(f"rows {len(chosen)}/{passed}  missing {len(missing)}  doubtful {len(set(doubt))}  "
          f"order-fixed {swapped}  filled-from-loose {len(filled)} {filled[:20]}")
    if missing:
        attempt = int(os.environ.get("ATTEMPT") or 1)
        dry_run = os.environ.get("DRY_RUN") == "true"
        print(f"missing numbers: {missing[:40]}")
        if attempt >= 3 or len(missing) <= MAX_UNREADABLE(passed):
            for n in missing:
                chosen[n] = "(NOT READABLE - SEE OFFICIAL LIST)"; doubt.append(n)
            tg(f"⚠️ {job['title']}: published with {len(missing)} unreadable row(s): numbers {missing[:30]}. Please fill them in from the official list.")
            missing = []
        else:
            tg(f"⚠️ {job['title']}: {len(missing)} numbers not read yet {missing[:15]}. Attempt {attempt} of 3.")
            info_str = json.dumps(job.get("info") or {})
            cmd = [
                "gh", "workflow", "run", "process.yml",
                "--ref", os.environ.get("GITHUB_REF_NAME", "main"),
                "-f", f"url={job['url']}",
                "-f", f"attempt={attempt + 1}",
                "-f", f"detected={job['detected']}",
                "-f", f"list={job.get('list', '')}",
                "-f", f"info={info_str}",
            ]
            for opt, env_k in (("list_url", "LIST_URL"), ("passed", "TEST_PASSED"), ("total", "TEST_TOTAL")):
                if os.environ.get(env_k):
                    cmd += ["-f", f"{opt}={os.environ[env_k]}"]
            if dry_run:
                cmd += ["-f", "dry_run=true"]
                print(f"DRY_RUN: {len(missing)} missing numbers; dispatching dry-run retry (attempt {attempt + 1}).")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"gh workflow run failed ({res.returncode}): {res.stderr.strip()}")
            sys.exit(1)
    if not job.get("passed"):
        has_eof = bool(job.get("has_nothing_follows")) or any(WORK.glob("eof_*.flag"))
        if not has_eof:
            tg(f"⚠️ {job['title']}: total passer count was unknown and NOTHING FOLLOWS was not seen. Please verify the end of the official list: {job['url']}")
    rows = [[n, chosen[n]] for n in range(1, passed + 1)]
    meta = dict(slug=job["slug"], exam=job["exam"], month=job["month"], year=job["year"], title=job["title"],
                expected_lists=job.get("expected_lists") or 1, list_label=job.get("list_label") or "",
                source=job["url"], passed=job["passed"], examinees=job["total"], count=len(rows), method=how,
                review=sorted(set(doubt))[:100], updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                detected_at=job["detected"], published_on=job.get("published_on") or "", built_at=now_ms())
    (DATA / f"{job['slug']}.json").write_text(json.dumps({"meta": meta, "passers": rows}, ensure_ascii=False, separators=(",", ":")))
    out(slug=job["slug"])
    if doubt:
        d = sorted(set(doubt))
        tg(f"ℹ️ {job['title']}\nPublished all {len(rows)} names. {len(d)} look less certain (numbers {d[:30]}). Please spot-check them.")
    print("built", job["slug"], len(rows), how)


if __name__ == "__main__":
    main()
