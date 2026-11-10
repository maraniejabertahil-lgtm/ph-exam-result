import json, subprocess, sys
from collections import Counter
from common import *


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
    cand = {}
    for f in files:
        for r in json.loads(f.read_text()):
            for k, v in r.items():
                cand.setdefault(int(k), Counter())[v] += 1
    passed = job.get("passed") or max(cand, default=0)
    chosen, doubt = {}, []
    for n, c in cand.items():
        name, top = c.most_common(1)[0]
        chosen[n] = name
        if how != "text" and (top / sum(c.values()) < 0.67 or not NAME_OK.match(name)):
            doubt.append(n)
    missing = [n for n in range(1, passed + 1) if n not in chosen]
    print(f"rows {len(chosen)}/{passed}  missing {len(missing)}  doubtful {len(doubt)}")
    if missing:
        attempt = int(os.environ.get("ATTEMPT") or 1)
        tg(f"⚠️ {job['title']}: {len(missing)} numbers not read yet {missing[:15]}. Attempt {attempt} of 3.")
        if attempt < 3:
            subprocess.run(["gh", "workflow", "run", "process.yml", "-f", f"url={job['url']}",
                            "-f", f"attempt={attempt + 1}", "-f", f"detected={job['detected']}"])
        sys.exit(1)
    rows = [[n, chosen[n]] for n in range(1, passed + 1)]
    meta = dict(slug=job["slug"], exam=job["exam"], month=job["month"], year=job["year"], title=job["title"],
                source=job["url"], passed=job["passed"], examinees=job["total"], count=len(rows), method=how,
                review=doubt[:100], updated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    (DATA / f"{job['slug']}.json").write_text(json.dumps({"meta": meta, "passers": rows}, ensure_ascii=False, separators=(",", ":")))
    state["upcoming"] = [u for u in state["upcoming"] if u["slug"] != job["slug"]]
    state_f.write_text(json.dumps(state, indent=1))
    (DATA / "pending.json").write_text(json.dumps(dict(meta, detected_at=job["detected"], built_at=now_ms())))
    if doubt:
        tg(f"ℹ️ {job['title']}\nPublished all {len(rows)} names. {len(doubt)} look less certain (numbers {doubt[:30]}). Please spot-check them.")
    print("built", job["slug"], len(rows), how)


if __name__ == "__main__":
    main()
