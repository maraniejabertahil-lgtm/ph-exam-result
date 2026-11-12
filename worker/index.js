// FREE-plan friendly: no PDF work here (10 ms CPU limit). It watches PRC articles, pulls out the facts below, and wakes GitHub Actions.
//   A. upcoming release: target date, changed date, delay/postponement, new announcements
//   B. results: exam name + date, article link, official list link(s) (Drive/PDF), published date/time
const MON = "january|february|march|april|may|june|july|august|september|october|november|december";
const MM = `(?:${MON})(?:-(?:and|to)-(?:${MON}))*`;
const RESULT = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(result|released)`);
const SCHED = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(schedule|room-assignment)`);
const ABOUT_EXAM = /licen[sc]ure|board[\s-]exam|examination/i;
const ABOUT_NEWS = /result|releas|postpon|delay|defer|resched|schedule|room[\s-]assignment|advisory|announc|passers/i;
const DELAY = /postpon|defer(?:red)?|delay|resched|moved to|pushed back|suspend|moved from/i;
const DATE = `(?:${MON})\\s+\\d{1,2}(?:\\s*(?:-|–|—|to|and|&)\\s*\\d{1,2})?,?\\s+20\\d\\d`;
const DATE_RE = new RegExp(DATE, "i");
const POSTED_RE = new RegExp(`(?:posted|published|date)\\s*[:\\-]?\\s*(${DATE}(?:[, ]+\\d{1,2}:\\d\\d\\s*(?:am|pm)?)?)`, "i");
const WITHIN_RE = /within\s+(?:the\s+)?(?:next\s+)?(\d{1,2}|one|two|three|four|five|six|seven|ten)\s+(?:\(\d+\)\s+)?(working|business|calendar)?\s*days?/i;
const LIST_RE = /(?:list|roll)\s+of\s+successful|passers|successful\s+examinees/i;
const MONTHS = MON.split("|");
const RECHECK_EVERY = 5, FRESH_DAYS = 14, MAX_NEW = 5, MAX_RECHECK = 3;   // keeps us far below the 50 subrequest / 10 ms CPU free limits

const pad = n => String(n).padStart(2, "0");
const toISO = raw => {                          // "December 5-7, 2026" -> "2026-12-05" (first day)
  const m = raw && raw.match(new RegExp(`(${MON})\\s+(\\d{1,2})`, "i")), y = raw && raw.match(/20\d\d/);
  return m && y ? `${y[0]}-${pad(MONTHS.indexOf(m[1].toLowerCase()) + 1)}-${pad(+m[2])}` : null;
};
const repoOf = v => String(v || "").replace(/^https?:\/\/(www\.)?github\.com\//i, "").replace(/\.git$/i, "").replace(/\/+$/, "");
const sum = s => [...s].reduce((a, c) => a + c.charCodeAt(0), 0);
async function sha(s) { return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))).slice(0, 16); }

// Pull every fact we care about out of one PRC article page.
async function analyse(html, url, slug) {
  html = html.slice(0, 200000);
  const title = ((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || "").split("|")[0].replace(/\s+/g, " ").trim();
  const pub = (html.match(/(?:article:published_time|datePublished)["'][^>]*content=["']([^"']+)/i)
    || html.match(/content=["']([^"']+)["'][^>]*property=["']article:published_time/i)
    || html.match(/<time[^>]*datetime=["']([^"']+)/i) || [])[1] || null;
  const links = [];
  for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#]+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const text = m[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(), href = m[1];
    if (!(LIST_RE.test(text) || /drive\.google\.com|docs\.google\.com|\.pdf(?:$|\?)/i.test(href))) continue;
    const abs = new URL(href, url).href;
    if (!links.some(l => l.href === abs) && links.length < 10) links.push({ text: text.slice(0, 120), href: abs });
  }
  const text = html.replace(/<(script|style|head|title)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
  const posted = (text.match(POSTED_RE) || [])[1] || pub;
  const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.length < 400 && /releas|post|publish|available|announc|resched|postpon|delay/i.test(s) && (DATE_RE.test(s) || WITHIN_RE.test(s))).slice(0, 5);
  const dateHit = sentences.map(s => s.match(DATE_RE)).find(Boolean), within = sentences.map(s => s.match(WITHIN_RE)).find(Boolean);
  const delayed = DELAY.test(title) || sentences.some(s => DELAY.test(s));
  const isResult = RESULT.test(slug) || links.some(l => /(?:list|roll)\s+of\s+successful/i.test(l.text));
  const info = {
    title, published_at: posted, release_date: dateHit ? toISO(dateHit[0]) : null, release_date_text: dateHit ? dateHit[0] : null,
    release_within: within ? within[0] : null, status: delayed ? "delayed" : (isResult ? "released" : "scheduled"),
    note: sentences[0] || null, links,
  };
  const kind = isResult && !delayed ? "result" : "announcement";
  // fingerprint of the facts only (not of ads/menus), so a changed date, delay or new link is noticed
  const hash = await sha(JSON.stringify([title, info.release_date, info.release_within, info.status, links.map(l => l.href)]));
  return { kind, info, hash };
}

async function fire(env, repo, url, kind, info, extra = {}) {
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, { method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "ph-exam-result", "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ event_type: "prc", client_payload: { url, kind, detected_at: Date.now(), info: { ...info, ...extra } } }) });
    return { ok: r.status === 204, status: r.status, body: r.status === 204 ? "" : (await r.text()).slice(0, 200) };
  } catch (e) { return { ok: false, status: 0, body: String(e).slice(0, 200) }; }
}

async function detect(env) {
  const now = Date.now(), minute = Math.floor(now / 60000), errors = [], repo = repoOf(env.GITHUB_REPO);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) errors.push(`GITHUB_REPO must look like owner/repo (got "${env.GITHUB_REPO}")`);
  const rawT = await env.KV.get("tracked"), rawS = await env.KV.get("seen");
  const firstRun = rawT === null && rawS === null;
  const tracked = JSON.parse(rawT || "{}"); let dirty = false;
  for (const u of JSON.parse(rawS || "[]")) if (!tracked[u]) { tracked[u] = { slug: u.split("/").pop(), first: now, hash: null, sent: true }; dirty = true; }   // migrate old "seen" list silently
  const w = (env.WATCH || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);

  // 1) listing pages -> relevant articles
  const found = [];
  for (const page of (minute % 10 === 0 ? [0, 1] : [0])) {
    try {
      const res = await fetch(`https://prc.gov.ph/articles?page=${page}`, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } });
      if (!res.ok) { errors.push(`prc.gov.ph listing page ${page}: HTTP ${res.status}`); continue; }
      const html = await res.text(); let n = 0;
      for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#?]*\/article\/([a-z0-9-]+))["'][^>]*>([\s\S]*?)<\/a>/gi)) {
        const url = new URL(m[1], "https://prc.gov.ph").href, slug = m[2], label = m[3].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().toLowerCase(), hay = `${slug} ${label}`;
        n++;
        if (found.some(f => f.url === url)) continue;
        if (!(RESULT.test(slug) || SCHED.test(slug) || (ABOUT_EXAM.test(hay) && ABOUT_NEWS.test(hay)))) continue;
        if (w.length && !w.some(x => hay.includes(x))) continue;
        found.push({ url, slug });
      }
      if (!n) errors.push(`prc.gov.ph listing page ${page}: no article links found (page layout changed or request blocked)`);
    } catch (e) { errors.push(`prc.gov.ph listing page ${page}: ${String(e).slice(0, 120)}`); }
  }

  // 2) decide which articles to open: new ones, ones whose last dispatch failed, and a rotating re-check of recent ones (catches edited dates / delays)
  const fresh = found.filter(f => !tracked[f.url]);
  if (firstRun) {                                    // first run only records what already exists (no old-result spam)
    for (const f of found) tracked[f.url] = { slug: f.slug, first: now, hash: null, sent: true };
    await env.KV.put("tracked", JSON.stringify(tracked)); await env.KV.put("last_run", JSON.stringify({ at: now, first_run: true, found: found.length, errors })); return;
  }
  const retry = Object.entries(tracked).filter(([, r]) => r.sent === false).map(([url, r]) => ({ url, slug: r.slug }));
  const recheck = Object.entries(tracked).filter(([u, r]) => r.sent !== false && now - r.first < FRESH_DAYS * 864e5 && (minute + sum(u)) % RECHECK_EVERY === 0).map(([url, r]) => ({ url, slug: r.slug })).slice(0, MAX_RECHECK);
  const todo = [...fresh.slice(0, MAX_NEW), ...retry.slice(0, 3), ...recheck].filter((t, i, a) => a.findIndex(x => x.url === t.url) === i);

  let fired = 0;
  for (const t of todo) {
    let html; try { const res = await fetch(t.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } }); if (!res.ok) { errors.push(`${t.slug}: HTTP ${res.status}`); continue; } html = await res.text(); } catch (e) { errors.push(`${t.slug}: ${String(e).slice(0, 100)}`); continue; }
    const a = await analyse(html, t.url, t.slug), rec = tracked[t.url];
    if (!rec) {                                                      // brand-new article
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
      tracked[t.url] = { slug: t.slug, first: now, hash: a.hash, sent: r.ok, release: a.info.release_date, status: a.info.status }; dirty = true;
      if (r.ok) fired++; else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (rec.sent === false) {                                 // earlier dispatch failed: try again
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
      Object.assign(rec, { hash: a.hash, sent: r.ok, release: a.info.release_date, status: a.info.status }); dirty = true;
      if (r.ok) fired++; else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (rec.hash === null) { Object.assign(rec, { hash: a.hash, release: a.info.release_date, status: a.info.status }); dirty = true;   // old article: remember as baseline, no alert
    } else if (a.hash !== rec.hash && a.kind === "announcement") {   // known announcement whose date / status / links changed
      const change = a.info.status === "delayed" && rec.status !== "delayed" ? "delayed" : (a.info.release_date !== rec.release ? "date-changed" : "updated");
      const r = await fire(env, repo, t.url, a.kind, a.info, { change, previous_release_date: rec.release || null });
      if (r.ok) { Object.assign(rec, { hash: a.hash, release: a.info.release_date, status: a.info.status }); dirty = true; fired++; } else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (a.hash !== rec.hash) { rec.hash = a.hash; dirty = true; }
  }
  if (dirty) {
    const keep = Object.entries(tracked).sort((x, y) => y[1].first - x[1].first).slice(0, 150);
    await env.KV.put("tracked", JSON.stringify(Object.fromEntries(keep)));
  }
  const prev = await env.KV.get("last_run");                         // free KV = 1000 writes/day, so only write when something changed or hourly
  const snap = { at: now, found: found.length, opened: todo.length, fired, errors };
  if (fired || errors.length || minute % 60 === 0 || !prev) await env.KV.put("last_run", JSON.stringify(snap));
  if (errors.length) console.log("watcher:", JSON.stringify(errors));
}
 // FREE-plan friendly: no PDF work here (10 ms CPU limit). It watches PRC articles and wakes GitHub Actions.
//   A. upcoming release: target date, changed date, delay/postponement, new announcements
//   B. results: exam name + date, article link, official list link(s) (Drive/PDF), published date
const MON = "january|february|march|april|may|june|july|august|september|october|november|december";
const MM = `(?:${MON})(?:-(?:and|to)-(?:${MON}))*`;
const RESULT = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(result|released)`);
const SCHED = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(schedule|room-assignment)`);
const ABOUT_EXAM = /licen[sc]ure|board[\s-]exam|examination/i;
const ABOUT_NEWS = /result|releas|postpon|delay|defer|resched|schedule|room[\s-]assignment|advisory|announc|passers/i;
const DELAY = /postpon|defer(?:red)?|delay|resched|moved to|pushed back|suspend|moved from/i;
const DATE = `(?:${MON})\\s+\\d{1,2}(?:\\s*(?:-|–|—|to|and|&)\\s*\\d{1,2})?,?\\s+20\\d\\d`;
const DATE_RE = new RegExp(DATE, "i");
const DMY = `\\d{1,2}\\s+(?:${MON}),?\\s+20\\d\\d`;   // PRC style: "2 December, 2025"
const POSTED_RE = new RegExp(`(?:posted(?:\\s+on)?|published(?:\\s+on)?|date)\\s*[:\\-]?\\s*(${DMY}|${DATE})(?:[, ]+(\\d{1,2}:\\d\\d\\s*(?:am|pm)?))?`, "i");
const WITHIN_RE = /within\s+(?:the\s+)?(?:next\s+)?(\d{1,2}|one|two|three|four|five|six|seven|ten)\s+(?:\(\d+\)\s+)?(working|business|calendar)?\s*days?/i;
const TURNAROUND_RE = /(?:released?\s+)?(?:in|within)\s+(?:[a-z-]+\s+)?\((\d{1,3})\)\s+(?:working|business|calendar)?\s*days?|immediately\s+after\s+the\s+examination/i;
const LIST_RE = /(?:list|roll)\s+of\s+successful|passers|successful\s+examinees/i;
const MONTHS = MON.split("|");
const RECHECK_EVERY = 5, FRESH_DAYS = 14, MAX_NEW = 5, MAX_RECHECK = 3;

const pad = n => String(n).padStart(2, "0");
const toISO = raw => {   // "December 5-7, 2026" or "5 December, 2026" -> "2026-12-05"
  const y = raw && raw.match(/20\d\d/); if (!y) return null;
  const a = raw.match(new RegExp(`(${MON})\\s+(\\d{1,2})`, "i")), b = raw.match(new RegExp(`(\\d{1,2})\\s+(${MON})`, "i"));
  const mo = a ? a[1] : b ? b[2] : null, d = a ? a[2] : b ? b[1] : null;
  return mo ? `${y[0]}-${pad(MONTHS.indexOf(mo.toLowerCase()) + 1)}-${pad(+d)}` : null;
};
const repoOf = v => String(v || "").replace(/^https?:\/\/(www\.)?github\.com\//i, "").replace(/\.git$/i, "").replace(/\/+$/, "");
const sum = s => [...s].reduce((a, c) => a + c.charCodeAt(0), 0);
async function sha(s) { return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))).slice(0, 16); }

// Pull every fact we care about out of one PRC article page.
async function analyse(html, url, slug) {
  html = html.slice(0, 200000);
  const title = ((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || "").split("|")[0].replace(/\s+/g, " ").trim();
  const pub = (html.match(/(?:article:published_time|datePublished)["'][^>]*content=["']([^"']+)/i)
    || html.match(/content=["']([^"']+)["'][^>]*property=["']article:published_time/i)
    || html.match(/<time[^>]*datetime=["']([^"']+)/i) || [])[1] || null;
  const links = [];
  for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#]+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const text = m[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(), href = m[1];
    if (!(LIST_RE.test(text) || /drive\.google\.com|docs\.google\.com|\.pdf(?:$|\?)/i.test(href))) continue;
    const abs = new URL(href, url).href;
    if (!links.some(l => l.href === abs) && links.length < 10) links.push({ text: text.slice(0, 120), href: abs });
  }
  const text = html.replace(/<(script|style|head|title)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
  const posted = (text.match(POSTED_RE) || [])[1] || pub;
  const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.length < 400 && /releas|post|publish|available|announc|resched|postpon|delay/i.test(s) && (DATE_RE.test(s) || WITHIN_RE.test(s))).slice(0, 5);
  const dateHit = sentences.map(s => s.match(DATE_RE)).find(Boolean), within = sentences.map(s => s.match(WITHIN_RE)).find(Boolean);
  const delayed = DELAY.test(title) || sentences.some(s => DELAY.test(s));
  const isResult = RESULT.test(slug) || links.some(l => /(?:list|roll)\s+of\s+successful/i.test(l.text));
  const info = {
    title, published_at: posted, release_date: dateHit ? toISO(dateHit[0]) : null, release_date_text: dateHit ? dateHit[0] : null,
    release_within: (title.match(TURNAROUND_RE) || within || [])[0] || null, status: delayed ? "delayed" : (isResult ? "released" : "scheduled"),
    note: sentences[0] || null, links,
  };
  const kind = isResult && !delayed ? "result" : "announcement";
  const hash = await sha(JSON.stringify([title, info.release_date, info.release_within, info.status, links.map(l => l.href)]));
  return { kind, info, hash };
}

async function fire(env, repo, url, kind, info, extra = {}) {
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, { method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "ph-exam-result", "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ event_type: "prc", client_payload: { url, kind, detected_at: Date.now(), info: { ...info, ...extra } } }) });
    return { ok: r.status === 204, status: r.status, body: r.status === 204 ? "" : (await r.text()).slice(0, 200) };
  } catch (e) { return { ok: false, status: 0, body: String(e).slice(0, 200) }; }
}

async function detect(env) {
  const now = Date.now(), minute = Math.floor(now / 60000), errors = [], repo = repoOf(env.GITHUB_REPO);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) errors.push(`GITHUB_REPO must look like owner/repo (got "${env.GITHUB_REPO}")`);
  const rawT = await env.KV.get("tracked"), rawS = await env.KV.get("seen");
  const firstRun = rawT === null && rawS === null;
  const tracked = JSON.parse(rawT || "{}"); let dirty = false;
  for (const u of JSON.parse(rawS || "[]")) if (!tracked[u]) { tracked[u] = { slug: u.split("/").pop(), first: now, hash: null, sent: true }; dirty = true; }
  const w = (env.WATCH || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);

  // 1) listing pages -> relevant articles
  const found = [];
  const feeds = ["https://www.prc.gov.ph/articles/exam-results?page=0", "https://www.prc.gov.ph/articles?page=0"];
  if (minute % 10 === 0) feeds.push("https://www.prc.gov.ph/articles/exam-results?page=1", "https://www.prc.gov.ph/articles?page=1");
  for (const feed of feeds) {
    const page = feed.replace("https://www.prc.gov.ph", "");
    try {
      const res = await fetch(feed, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } });
      if (!res.ok) { errors.push(`prc.gov.ph listing ${page}: HTTP ${res.status}`); continue; }
      const html = await res.text(); let n = 0;
      for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#?]*\/article\/([a-z0-9-]+))["'][^>]*>([\s\S]*?)<\/a>/gi)) {
        const url = new URL(m[1], "https://www.prc.gov.ph").href, slug = m[2], label = m[3].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().toLowerCase(), hay = `${slug} ${label}`;
        n++;
        if (found.some(f => f.url === url)) continue;
        if (!(RESULT.test(slug) || SCHED.test(slug) || (ABOUT_EXAM.test(hay) && ABOUT_NEWS.test(hay)))) continue;
        if (w.length && !w.some(x => hay.includes(x))) continue;
        found.push({ url, slug });
      }
      if (!n) errors.push(`prc.gov.ph listing ${page}: no article links found (layout changed or request blocked)`);
    } catch (e) { errors.push(`prc.gov.ph listing ${page}: ${String(e).slice(0, 120)}`); }
  }

  // 2) pinned yearly schedule article (its attached PDF holds the target release dates)
  for (const u of (env.PIN || "https://www.prc.gov.ph/article/schedule-licensure-examinations-year-2026").split(",").map(x => x.trim()).filter(Boolean))
    if (!found.some(f => f.url === u)) found.push({ url: u, slug: u.split("/").pop() });
  const fresh = found.filter(f => !tracked[f.url]);
  if (firstRun) {   // first run only records what already exists (no old-result spam)
    for (const f of found) tracked[f.url] = { slug: f.slug, first: now, hash: null, sent: true };
    await env.KV.put("tracked", JSON.stringify(tracked)); await env.KV.put("last_run", JSON.stringify({ at: now, first_run: true, found: found.length, errors })); return;
  }
  const retry = Object.entries(tracked).filter(([, r]) => r.sent === false).map(([url, r]) => ({ url, slug: r.slug }));
  const recheck = Object.entries(tracked).filter(([u, r]) => r.sent !== false && now - r.first < FRESH_DAYS * 864e5 && (minute + sum(u)) % RECHECK_EVERY === 0).map(([url, r]) => ({ url, slug: r.slug })).slice(0, MAX_RECHECK);
  const todo = [...fresh.slice(0, MAX_NEW), ...retry.slice(0, 3), ...recheck].filter((t, i, a) => a.findIndex(x => x.url === t.url) === i);

  let fired = 0;
  for (const t of todo) {
    let html; try { const res = await fetch(t.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } }); if (!res.ok) { errors.push(`${t.slug}: HTTP ${res.status}`); continue; } html = await res.text(); } catch (e) { errors.push(`${t.slug}: ${String(e).slice(0, 100)}`); continue; }
    const a = await analyse(html, t.url, t.slug), rec = tracked[t.url];
    if (!rec) {   // brand-new article
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
      tracked[t.url] = { slug: t.slug, first: now, hash: a.hash, sent: r.ok, release: a.info.release_date, status: a.info.status }; dirty = true;
      if (r.ok) fired++; else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (rec.sent === false) {   // earlier dispatch failed: try again
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
      Object.assign(rec, { hash: a.hash, sent: r.ok, release: a.info.release_date, status: a.info.status }); dirty = true;
      if (r.ok) fired++; else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (rec.hash === null) {   // old article: remember as baseline, no alert
      Object.assign(rec, { hash: a.hash, release: a.info.release_date, status: a.info.status }); dirty = true;
    } else if (a.hash !== rec.hash && a.kind === "announcement") {   // date / status / links changed
      const change = a.info.status === "delayed" && rec.status !== "delayed" ? "delayed" : (a.info.release_date !== rec.release ? "date-changed" : "updated");
      const r = await fire(env, repo, t.url, a.kind, a.info, { change, previous_release_date: rec.release || null });
      if (r.ok) { Object.assign(rec, { hash: a.hash, release: a.info.release_date, status: a.info.status }); dirty = true; fired++; } else errors.push(`dispatch ${t.slug}: HTTP ${r.status} ${r.body}`);
    } else if (a.hash !== rec.hash) { rec.hash = a.hash; dirty = true; }
  }
  if (dirty) {
    const keep = Object.entries(tracked).sort((x, y) => y[1].first - x[1].first).slice(0, 150);
    await env.KV.put("tracked", JSON.stringify(Object.fromEntries(keep)));
  }
  const prev = await env.KV.get("last_run");   // free KV = 1000 writes/day: write only on change or hourly
  const snap = { at: now, found: found.length, opened: todo.length, fired, errors };
  if (fired || errors.length || minute % 60 === 0 || !prev) await env.KV.put("last_run", JSON.stringify(snap));
  if (errors.length) console.log("watcher:", JSON.stringify(errors));
}

// ---- Owner login: Firebase Auth checks the password, Firestore owners/{uid} is the allow-list ----
const enc = new TextEncoder(), hex = b => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, "0")).join("");
async function sign(env, v) { const k = await crypto.subtle.importKey("raw", enc.encode(env.SESSION_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]); return hex(await crypto.subtle.sign("HMAC", k, enc.encode(v))); }
const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const page = (b, h = {}) => new Response(`<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><meta name=robots content=noindex><body style="font:16px system-ui;max-width:760px;margin:auto;padding:16px">${b}`, { headers: { "content-type": "text/html;charset=utf-8", "cache-control": "no-store", ...h } });
async function authed(env, req) {
  const m = (req.headers.get("cookie") || "").match(/(?:^|; )s=([^;]+)/); if (!m) return false;
  const [uid, exp, sig] = decodeURIComponent(m[1]).split("."); return +exp > Date.now() && sig === await sign(env, `${uid}.${exp}`);
}
async function owner(req, env) {
  const p = new URL(req.url).pathname;
  if (p === "/owner/logout") return new Response(null, { status: 302, headers: { location: "/", "set-cookie": "s=; Max-Age=0; Path=/" } });
  const form = e => page(`<h2>Owner login</h2>${e ? `<p style=color:#c00>${e}</p>` : ""}<form method=post action=/owner/login><input name=email type=email placeholder=Email required style=width:100%;padding:10px><br><br><input name=password type=password placeholder=Password required style=width:100%;padding:10px><br><br><button style=padding:10px>Sign in</button></form>`);
  if (p === "/owner/login") {
    if (req.method !== "POST") return form("");
    const f = await req.formData();
    const r = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${env.FIREBASE_API_KEY}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: f.get("email"), password: f.get("password"), returnSecureToken: true }) });
    if (!r.ok) return form("Invalid login.");
    const { idToken, localId } = await r.json();
    const d = await fetch(`https://firestore.googleapis.com/v1/projects/${env.FIREBASE_PROJECT_ID}/databases/(default)/documents/owners/${localId}`, { headers: { Authorization: `Bearer ${idToken}` } });
    if (!d.ok) return form("Not an owner.");
    const exp = Date.now() + 12 * 3600e3;
    return new Response(null, { status: 302, headers: { location: "/owner", "set-cookie": `s=${encodeURIComponent(`${localId}.${exp}.${await sign(env, `${localId}.${exp}`)}`)}; Max-Age=43200; Path=/; HttpOnly; Secure; SameSite=Strict` } });
  }
  if (!(await authed(env, req))) return new Response(null, { status: 302, headers: { location: "/owner/login" } });
  let rel = []; try { rel = await (await fetch(`${env.SITE_URL}/data/releases.json`)).json(); } catch {}
  return page(`<h2>Owner dashboard <small><a href=/owner/logout>sign out</a></small></h2>
<h3>Releases (detection → live)</h3><table border=0 cellpadding=6 style=width:100%><tr><th align=left>Exam<th>Passers<th>Live in<th>Method<th>TG<th>FB</tr>${rel.map(r => `<tr><td>${E(r.exam)} ${E(r.month)} ${r.year}<td>${r.count}<td>${r.live_secs}s<td>${E(r.method)}<td>${E(r.tg)}<td>${E(r.fb)}</tr>`).join("") || "<tr><td colspan=6>No releases yet</tr>"}</table>
<h3>Visitors &amp; sources</h3><p><a href="https://dash.cloudflare.com/?to=/:account/web-analytics">Cloudflare Web Analytics</a> (free: visitors, pages, countries, referrers) · <a href="https://search.google.com/search-console">Search Console</a> · <a href="https://www.google.com/adsense">AdSense earnings</a> (after you add ads)</p>`);
}

export default {
  scheduled(_e, env, ctx) { ctx.waitUntil(detect(env)); },
  async fetch(req, env) {
    const p = new URL(req.url).pathname;
    if (p === "/health") return new Response(JSON.stringify({ last_run: JSON.parse((await env.KV.get("last_run")) || "null"), tracked: Object.keys(JSON.parse((await env.KV.get("tracked")) || "{}")).length }), { headers: { "content-type": "application/json" } });
    return p.startsWith("/owner") ? owner(req, env) : new Response("ok");
  },
};



