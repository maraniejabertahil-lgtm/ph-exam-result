// PH EXAM RESULT watcher - single self-contained Worker file (no imports).
// Part 1: official PRC future-release schedule reader.  Part 2: article watcher, /status, /api/releases/upcoming, owner login.

// ======== PART 1: PRC schedule reader ========
const USER_AGENT = "PH-EXAM-RESULTS-Watcher";
const RELEASE_SCHEDULE_CACHE_KEY = "official-release-schedule:v1";
const REFRESH_INTERVAL_MS = 60 * 1000;
const MAX_PUBLIC_SNAPSHOT_AGE_MS = 11 * 60 * 1000;   // ported: 5-min refresh + margin (KV free-tier write budget)
const SNAPSHOT_TTL_SECONDS = 14 * 24 * 60 * 60;
const MAX_HTML_BYTES = 1024 * 1024;
const MAX_ROBOTS_BYTES = 32 * 1024;
const MAX_REDIRECTS = 5;
const MANILA_OFFSET_MS = 8 * 60 * 60 * 1000;

function decodeEntities(value) {
  return String(value || "")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#(\d+);/g, (_m, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_m, n) => String.fromCodePoint(parseInt(n, 16)));
}

function cleanText(value) {
  return decodeEntities(String(value || "")
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function localManilaDate(now) {
  const shifted = new Date(now.getTime() + MANILA_OFFSET_MS);
  const year = shifted.getUTCFullYear();
  const month = shifted.getUTCMonth() + 1;
  const day = shifted.getUTCDate();
  return {
    year,
    iso: year + "-" + String(month).padStart(2, "0") + "-" + String(day).padStart(2, "0"),
    ordinal: Date.UTC(year, month - 1, day)
  };
}

function daysUntil(dateIso, now) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateIso);
  if (!parts) return null;
  const target = Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
  return Math.round((target - localManilaDate(now).ordinal) / 86400000);
}

function parseTargetDate(value) {
  const text = cleanText(value);
  const match = /\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})\b/i.exec(text);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[3]), new Date(Date.parse(match[1] + " 1, 2000")).getUTCMonth(), Number(match[2])));
  if (Number.isNaN(date.getTime()) || date.getUTCFullYear() !== Number(match[3]) || date.getUTCDate() !== Number(match[2])) return null;
  return date.getUTCFullYear() + "-" + String(date.getUTCMonth() + 1).padStart(2, "0") + "-" + String(date.getUTCDate()).padStart(2, "0");
}

function parseCells(rowHtml) {
  const cells = [];
  const expression = /<(th|td)\b([^>]*)>([\s\S]*?)<\/\1\s*>/gi;
  let match;
  while ((match = expression.exec(rowHtml)) !== null) {
    const colspanMatch = /\bcolspan\s*=\s*["']?(\d+)/i.exec(match[2]);
    const colspan = colspanMatch ? Math.max(1, Math.min(20, Number(colspanMatch[1]))) : 1;
    cells.push({ tag: match[1].toLowerCase(), text: cleanText(match[3]), colspan });
  }
  return cells;
}

function headerColumn(cells, predicate) {
  let logicalIndex = 0;
  for (const cell of cells) {
    if (predicate(cell.text.toUpperCase())) return logicalIndex;
    logicalIndex += cell.colspan;
  }
  return -1;
}

function deduplicateScheduleRows(rows) {
  const uniqueRows = new Map();
  for (const item of rows) {
    const examKey = String(item.exam || "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
    const key = examKey + "\u0000" + item.target_release_date;
    if (!uniqueRows.has(key)) uniqueRows.set(key, item);
  }
  return [...uniqueRows.values()];
}

function parsePrcScheduleHtml(html, sourceUrl, now = new Date()) {
  if (typeof html !== "string" || html.length === 0 || html.length > MAX_HTML_BYTES) {
    throw new Error("PRC schedule HTML is empty or exceeds the configured size limit.");
  }
  const tables = [...html.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table\s*>/gi)].map((match) => match[1]);
  let parsedRows = [];
  let foundScheduleTable = false;
  const unparsedTargetDates = [];

  for (const table of tables) {
    const rows = [...table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr\s*>/gi)].map((match) => match[1]);
    let headerRowIndex = -1;
    let nameIndex = -1;
    let releaseIndex = -1;

    for (let index = 0; index < rows.length; index += 1) {
      const cells = parseCells(rows[index]);
      const name = headerColumn(cells, (text) => text.includes("NAME OF EXAMINATION"));
      const release = headerColumn(cells, (text) => text.includes("TARGET DATE") && text.includes("RELEASE"));
      if (name >= 0 && release >= 0) {
        headerRowIndex = index;
        nameIndex = name;
        releaseIndex = release;
        foundScheduleTable = true;
        break;
      }
    }
    if (headerRowIndex < 0) continue;

    const scheduleYearMatch = new URL(sourceUrl).pathname.match(/\/(20\d{2})-schedule-examination\/?$/i);
    const scheduleYear = scheduleYearMatch ? Number(scheduleYearMatch[1]) : null;
    for (let index = headerRowIndex + 1; index < rows.length; index += 1) {
      const cells = parseCells(rows[index]);
      if (cells.length <= Math.max(nameIndex, releaseIndex)) continue;
      const exam = cells[nameIndex]?.text || "";
      const rawDate = cells[releaseIndex]?.text || "";
      if (!exam || !rawDate) continue;
      const date = parseTargetDate(rawDate);
      if (!date) {
        unparsedTargetDates.push({ exam: exam.slice(0, 160), label: rawDate.slice(0, 100) });
        continue;
      }
      const days = daysUntil(date, now);
      parsedRows.push({
        authority: "PRC",
        exam,
        schedule_year: scheduleYear,
        target_release_date: date,
        target_release_label: rawDate,
        days_until: days,
        status: days >= 0 ? "scheduled" : "past",
        source_url: sourceUrl
      });
    }
  }

  if (!foundScheduleTable || parsedRows.length === 0) {
    throw new Error("The PRC schedule table or its target-release columns could not be identified; manual review is required.");
  }

  // Collapse only exact logical duplicates: same normalized exam name AND target date.
  // Different exams on one date, and the same exam with different dates, remain separate.
  parsedRows = deduplicateScheduleRows(parsedRows);
  parsedRows.sort((a, b) => a.target_release_date.localeCompare(b.target_release_date) || a.exam.localeCompare(b.exam));
  const upcoming = parsedRows.filter((item) => item.days_until >= 0);
  return {
    authority: "PRC",
    source_url: sourceUrl,
    as_of_date_manila: localManilaDate(now).iso,
    parsed_count: parsedRows.length,
    upcoming_count: upcoming.length,
    unparsed_count: unparsedTargetDates.length,
    unparsed_target_dates: unparsedTargetDates.slice(0, 50),
    upcoming,
    nearest: upcoming[0] || null
  };
}

function discoverSchedulePageUrls(indexHtml, indexUrl, now = new Date(), maxPages = 2) {
  const origin = new URL(indexUrl).origin;
  const currentYear = localManilaDate(now).year;
  const links = new Map();
  const expression = /<a\b[^>]*\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>/gi;
  let match;
  while ((match = expression.exec(indexHtml)) !== null) {
    const href = decodeEntities(match[1] || match[2] || match[3] || "").trim();
    if (!href || href.startsWith("#") || /^javascript:/i.test(href)) continue;
    try {
      const url = new URL(href, indexUrl);
      if (url.protocol !== "https:" || url.origin !== origin || url.username || url.password || url.search || url.hash) continue;
      const yearMatch = /^\/(20\d{2})-schedule-examination\/?$/i.exec(url.pathname);
      if (!yearMatch) continue;
      const year = Number(yearMatch[1]);
      if (year < currentYear || year > currentYear + 1) continue;
      url.pathname = "/" + year + "-schedule-examination";
      links.set(year, url.href);
    } catch { /* Ignore malformed or non-official links. */ }
  }
  return [...links.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(0, Math.max(1, Math.min(2, maxPages)))
    .map(([year, url]) => ({ year, url }));
}

function robotsPatternMatches(pattern, path) {
  if (!pattern) return false;
  const endAnchored = pattern.endsWith("$");
  const body = endAnchored ? pattern.slice(0, -1) : pattern;
  const regex = "^" + body.split("*").map((part) => part.replace(/[-/\\^$+?.()|[\]{}]/g, "\\$&")).join(".*") + (endAnchored ? "$" : "");
  try { return new RegExp(regex).test(path); } catch { return false; }
}

function robotsAllowsPath(robotsText, path, userAgent = "PH-EXAM-RESULTS-Watcher") {
  const groups = [];
  let group = null;
  for (const rawLine of String(robotsText || "").split(/\r?\n/)) {
    const line = rawLine.split("#", 1)[0].trim();
    if (!line) continue;
    const agent = /^user-agent\s*:\s*(.+)$/i.exec(line);
    if (agent) {
      if (!group || group.hasRules) {
        group = { agents: [], rules: [], hasRules: false };
        groups.push(group);
      }
      group.agents.push(agent[1].trim().toLowerCase());
      continue;
    }
    const rule = /^(allow|disallow)\s*:\s*(.*)$/i.exec(line);
    if (rule && group) {
      group.rules.push({ allow: rule[1].toLowerCase() === "allow", pattern: rule[2].trim() });
      group.hasRules = true;
    }
  }

  const exact = groups.filter((item) => item.agents.includes(String(userAgent).toLowerCase()));
  const wildcard = groups.filter((item) => item.agents.includes("*"));
  const selected = exact.length ? exact : wildcard;
  const matches = selected.flatMap((item) => item.rules)
    .filter((rule) => rule.pattern && robotsPatternMatches(rule.pattern, path))
    .sort((a, b) => b.pattern.replace(/\*/g, "").length - a.pattern.replace(/\*/g, "").length);
  if (!matches.length) return true;
  const mostSpecific = matches[0].pattern.replace(/\*/g, "").length;
  const tied = matches.filter((rule) => rule.pattern.replace(/\*/g, "").length === mostSpecific);
  return tied.some((rule) => rule.allow);
}

async function fetchSameOrigin(urlValue, fetchImpl, robotsText = null) {
  const original = new URL(urlValue);
  if (original.protocol !== "https:" || original.username || original.password) {
    throw new Error("Only approved HTTPS URLs without embedded credentials are allowed.");
  }
  let current = original;
  for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects += 1) {
    if (robotsText !== null && !robotsAllowsPath(robotsText, current.pathname)) {
      const error = new Error("PRC robots.txt disallows automated access to " + current.pathname + ".");
      error.code = "ROBOTS_DISALLOWED";
      throw error;
    }
    const response = await fetchImpl(current.href, {
      method: "GET",
      redirect: "manual",
      headers: { "User-Agent": USER_AGENT, Accept: "text/html,text/plain;q=0.9,*/*;q=0.1" },
      signal: AbortSignal.timeout(10_000)
    });
    if (![301, 302, 303, 307, 308].includes(response.status)) return { response, finalUrl: current.href };
    const location = response.headers.get("location");
    if (!location) return { response, finalUrl: current.href };
    const next = new URL(location, current);
    if (next.protocol !== "https:" || next.origin !== original.origin || next.username || next.password) {
      throw new Error("Cross-origin or non-HTTPS redirect rejected.");
    }
    current = next;
  }
  throw new Error("Too many redirects while reading the official PRC schedule.");
}

async function readBoundedText(response, maxBytes) {
  const declared = Number(response.headers.get("content-length") || 0);
  if (declared > maxBytes) throw new Error("Official PRC response exceeds the configured size limit.");
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      total += result.value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new Error("Official PRC response exceeds the configured size limit.");
      }
      chunks.push(result.value);
    }
  } finally {
    try { reader.releaseLock(); } catch { /* no-op */ }
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

async function fetchText(url, fetchImpl, expectedType, maxBytes, robotsText = null) {
  const result = await fetchSameOrigin(url, fetchImpl, robotsText);
  if (result.response.status !== 200) {
    throw new Error("Official PRC source returned HTTP " + result.response.status + ".");
  }
  const contentType = (result.response.headers.get("content-type") || "").toLowerCase();
  if (expectedType && !contentType.includes(expectedType)) {
    throw new Error("Official PRC source returned an unexpected content type.");
  }
  return { text: await readBoundedText(result.response, maxBytes), finalUrl: result.finalUrl };
}

async function fetchRobotsPolicy(indexSource, fetchImpl, now) {
  const index = new URL(indexSource.url);
  const robotsUrl = new URL("/robots.txt", index.origin).href;
  const result = await fetchText(robotsUrl, fetchImpl, "text", MAX_ROBOTS_BYTES);
  if (!robotsAllowsPath(result.text, index.pathname, USER_AGENT)) {
    const error = new Error("PRC robots.txt disallows automated access to " + index.pathname + ".");
    error.code = "ROBOTS_DISALLOWED";
    throw error;
  }
  return { text: result.text, url: result.finalUrl, checked_at: now.toISOString(), user_agent: USER_AGENT, outcome: "allowed" };
}

async function refreshOfficialReleaseSchedule({ sources, kv, fetchImpl = fetch, now = new Date() }) {
  const source = Array.isArray(sources)
    ? sources.find((item) => item?.source_type === "official_schedule_index" && item.enabled === true && item.authorized === true)
    : null;
  if (!source || !kv || typeof kv.get !== "function" || typeof kv.put !== "function") {
    return { status: "not_configured", snapshot: null };
  }

  let raw;
  try {
    raw = await kv.get(RELEASE_SCHEDULE_CACHE_KEY);
  } catch {
    return { status: "cache_error", snapshot: null, error: "Could not read the official schedule cache." };
  }
  let cached = null;
  if (raw) {
    try { cached = JSON.parse(raw); } catch { cached = null; }
  }
  const fetchedAt = cached?.fetched_at ? Date.parse(cached.fetched_at) : NaN;
  const configuredMinutes = Number(source.refresh_interval_minutes);
  const configuredHours = Number(source.refresh_interval_hours);
  const refreshInterval = Number.isInteger(configuredMinutes) && configuredMinutes >= 1 && configuredMinutes <= 60
    ? configuredMinutes * 60 * 1000
    : Number.isInteger(configuredHours) && configuredHours >= 1 && configuredHours <= 24
      ? configuredHours * 60 * 60 * 1000
      : REFRESH_INTERVAL_MS;
  const hasCurrentRobotsEvidence = cached?.access_policy?.outcome === "allowed"
    && cached?.access_policy?.user_agent === USER_AGENT;
  if (cached && hasCurrentRobotsEvidence && Number.isFinite(fetchedAt) && now.getTime() >= fetchedAt && now.getTime() - fetchedAt < refreshInterval) {
    return { status: "cached", snapshot: cached };
  }

  try {
    const robotsPolicy = await fetchRobotsPolicy(source, fetchImpl, now);
    const indexResult = await fetchText(source.url, fetchImpl, "text/html", MAX_HTML_BYTES, robotsPolicy.text);
    const pages = discoverSchedulePageUrls(indexResult.text, indexResult.finalUrl, now, source.max_schedule_pages || 2);
    if (!pages.length) throw new Error("The official PRC schedule index did not link to a current or next-year schedule page.");

    const schedules = [];
    for (const page of pages) {
      const pageResult = await fetchText(page.url, fetchImpl, "text/html", MAX_HTML_BYTES, robotsPolicy.text);
      schedules.push(parsePrcScheduleHtml(pageResult.text, pageResult.finalUrl, now));
    }
    const upcoming = deduplicateScheduleRows(schedules.flatMap((item) => item.upcoming))
      .sort((a, b) => a.target_release_date.localeCompare(b.target_release_date) || a.exam.localeCompare(b.exam));
    const unparsed = schedules.flatMap((item) => item.unparsed_target_dates);
    const snapshot = {
      schema_version: 1,
      authority: "PRC",
      status: "official_schedule",
      fetched_at: now.toISOString(),
      as_of_date_manila: localManilaDate(now).iso,
      source_index_url: indexResult.finalUrl,
      source_pages: schedules.map((item) => item.source_url),
      access_policy: { robots_txt_url: robotsPolicy.url, robots_checked_at: robotsPolicy.checked_at, user_agent: robotsPolicy.user_agent, outcome: robotsPolicy.outcome },
      upcoming_count: upcoming.length,
      unparsed_count: unparsed.length,
      unparsed_target_dates: unparsed.slice(0, 50),
      upcoming,
      nearest: upcoming[0] || null
    };
    await kv.put(RELEASE_SCHEDULE_CACHE_KEY, JSON.stringify(snapshot), { expirationTtl: SNAPSHOT_TTL_SECONDS });
    return { status: unparsed.length ? "updated_with_unparsed_rows" : "updated", snapshot };
  } catch (error) {
    const code = error?.code === "ROBOTS_DISALLOWED" ? "robots_disallowed" : "refresh_error";
    return {
      status: cached ? "stale" : code,
      snapshot: cached,
      error: String(error?.message || error).slice(0, 240)
    };
  }
}

async function getReleaseScheduleResponse(request, env) {
  const url = new URL(request.url);
  const headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "public, max-age=300"
  };
  if (url.pathname !== "/api/releases/upcoming") {
    return new Response(JSON.stringify({ ok: false, error: "Not found." }), { status: 404, headers });
  }
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
  if (request.method !== "GET") {
    return new Response(JSON.stringify({ ok: false, error: "Method not allowed." }), { status: 405, headers });
  }
  try {
    const raw = await env?.PEAK_WEEK?.get(RELEASE_SCHEDULE_CACHE_KEY);
    if (!raw) {
      return new Response(JSON.stringify({ ok: false, status: "not_initialized", message: "The Watcher has not stored an official PRC schedule snapshot yet." }), {
        status: 503, headers
      });
    }
    const snapshot = JSON.parse(raw);
    const fetchedAt = snapshot?.fetched_at ? Date.parse(snapshot.fetched_at) : NaN;
    const ageMs = Number.isFinite(fetchedAt) ? Date.now() - fetchedAt : Infinity;
    if (ageMs < 0 || ageMs > MAX_PUBLIC_SNAPSHOT_AGE_MS) {
      return new Response(JSON.stringify({
        ok: false,
        status: "stale",
        message: "The official PRC schedule has not been refreshed recently. Please try again shortly.",
        fetched_at: snapshot?.fetched_at || null,
        max_age_ms: MAX_PUBLIC_SNAPSHOT_AGE_MS
      }), { status: 503, headers: { ...headers, "Cache-Control": "no-store" } });
    }
    const today = localManilaDate(new Date()).iso;
    const upcoming = (Array.isArray(snapshot.upcoming) ? snapshot.upcoming : [])
      .filter((item) => typeof item?.target_release_date === "string" && item.target_release_date >= today)
      .map((item) => ({ ...item, days_until: daysUntil(item.target_release_date, new Date()), status: "scheduled" }));
    return new Response(JSON.stringify({
      ok: true,
      ...snapshot,
      as_of_date_manila: today,
      upcoming_count: upcoming.length,
      upcoming,
      nearest: upcoming[0] || null
    }), { status: 200, headers: { ...headers, "Cache-Control": "no-store" } });
  } catch {
    return new Response(JSON.stringify({ ok: false, status: "unavailable", message: "The official PRC schedule snapshot is temporarily unavailable." }), {
      status: 503, headers
    });
  }
}

// ======== PART 2: watcher + routes ========
// FREE-plan friendly: no PDF work here (10 ms CPU limit). It watches PRC articles, pulls out the facts below, and wakes GitHub Actions.
//   A. upcoming release: target date, changed date, delay/postponement, new announcements
//   B. results: exam name + date, article link, official list link(s) (Drive/PDF), published date/time
// Official PRC future-release schedule (target dates only; not proof a result is published).
const SCHEDULE_SOURCES = [{
  id: "PRC-OFFICIAL-SCHEDULE-INDEX", authority: "PRC", source_type: "official_schedule_index",
  enabled: true, authorized: true, url: "https://www.prc.gov.ph/exam-schedules-menu",
  max_schedule_pages: 2, refresh_interval_minutes: 5
}];

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

// ---- Event log for the owner dashboard (/status). Stored in KV; duplicates are suppressed for 1 hour to protect the free KV write limit. ----
let EV = null;
const note = (type, msg) => { if (EV) EV.push({ t: Date.now(), type, msg: String(msg).slice(0, 300) }); };
async function recordEvents(env, ev) {
  if (!ev.length) return;
  let list = []; try { list = JSON.parse((await env.KV.get("events")) || "[]"); } catch {}
  const cutoff = Date.now() - 3600e3, add = [];
  for (const e of ev) if (!list.some(x => x.type === e.type && x.msg === e.msg && x.t > cutoff) && !add.some(x => x.type === e.type && x.msg === e.msg)) add.push(e);
  if (add.length) await env.KV.put("events", JSON.stringify([...add.reverse(), ...list].slice(0, 60)));   // newest first
}

async function fire(env, repo, url, kind, info, extra = {}) {
  let out;
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, { method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "ph-exam-result", "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ event_type: "prc", client_payload: { url, kind, detected_at: Date.now(), info: { ...info, ...extra } } }) });
    out = { ok: r.status === 204, status: r.status, body: r.status === 204 ? "" : (await r.text()).slice(0, 200) };
  } catch (e) { out = { ok: false, status: 0, body: String(e).slice(0, 200) }; }
  const what = `${kind} ${url.split("/").pop()} (${extra.change || "new"}${info.release_date ? ", release " + info.release_date : ""})`;
  note(out.ok ? "dispatched" : "error", out.ok ? `Sent to GitHub: ${what}` : `GitHub dispatch failed, HTTP ${out.status}: ${what}`);
  return out;
}

async function detect(env) {
  const now = Date.now(), minute = Math.floor(now / 60000), errors = [], repo = repoOf(env.GITHUB_REPO);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) errors.push(`GITHUB_REPO must look like owner/repo (got "${env.GITHUB_REPO}")`);
  const rawT = await env.KV.get("tracked"), rawS = await env.KV.get("seen");
  const firstRun = rawT === null && rawS === null;
  const tracked = JSON.parse(rawT || "{}"); let dirty = false;
  for (const u of JSON.parse(rawS || "[]")) if (!tracked[u]) { tracked[u] = { slug: u.split("/").pop(), first: now, hash: null, sent: true }; dirty = true; }   // migrate old "seen" list silently
  const w = (env.WATCH || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);

  // 1) PRC Exam Results tab (/articles/exam-results) -> relevant articles.
  // The General News list (/articles) is busy with other posts, so result announcements can be pushed off it.
  // The www host is tried first; the bare domain is a fallback because it returned HTTP 521/504 during outages.
  const found = [];
  const LISTING_HOSTS = ["https://www.prc.gov.ph", "https://prc.gov.ph"];
  for (const page of [0, 1]) {
    let html = null, lastError = "";
    for (const host of LISTING_HOSTS) {
      try {
        const res = await fetch(`${host}/articles/exam-results?page=${page}`, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } });
        if (!res.ok) { lastError = `HTTP ${res.status} from ${host}`; continue; }
        html = await res.text();
        break;
      } catch (e) { lastError = `${host}: ${String(e).slice(0, 100)}`; }
    }
    if (html === null) { errors.push(`prc.gov.ph exam-results page ${page}: ${lastError}`); continue; }
    let n = 0;
    for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#?]*\/article\/([a-z0-9-]+))["'][^>]*>([\s\S]*?)<\/a>/gi)) {
      const url = new URL(m[1], "https://www.prc.gov.ph").href, slug = m[2], label = m[3].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().toLowerCase(), hay = `${slug} ${label}`;
      n++;
      if (found.some(f => f.url === url)) continue;
      if (!(RESULT.test(slug) || SCHED.test(slug) || (ABOUT_EXAM.test(hay) && ABOUT_NEWS.test(hay)))) continue;
      if (w.length && !w.some(x => hay.includes(x))) continue;
      found.push({ url, slug });
    }
    if (!n) errors.push(`prc.gov.ph exam-results page ${page}: no article links found (page layout changed or request blocked)`);
  }

  // 2) decide which articles to open: new ones, ones whose last dispatch failed, and a rotating re-check of recent ones (catches edited dates / delays)
  const fresh = found.filter(f => !tracked[f.url])
    .sort((a, b) => Number(RESULT.test(b.slug)) - Number(RESULT.test(a.slug)));   // result articles first
  if (firstRun) {                                    // first run only records what already exists (no old-result spam)
    for (const f of found) tracked[f.url] = { slug: f.slug, first: now, hash: null, sent: true };
    note("info", `First run: remembered ${found.length} existing PRC articles (no alerts sent for old ones).`);
    for (const m of errors) note("error", m);
    await env.KV.put("tracked", JSON.stringify(tracked)); await env.KV.put("last_run", JSON.stringify({ at: now, first_run: true, found: found.length, errors })); return;
  }
  const retry = Object.entries(tracked).filter(([, r]) => r.sent === false).map(([url, r]) => ({ url, slug: r.slug }))
    .sort((a, b) => Number(RESULT.test(b.slug)) - Number(RESULT.test(a.slug)));   // failed result dispatches first
  const recheck = Object.entries(tracked).filter(([u, r]) => r.sent !== false && now - r.first < FRESH_DAYS * 864e5 && (minute + sum(u)) % RECHECK_EVERY === 0).map(([url, r]) => ({ url, slug: r.slug })).slice(0, MAX_RECHECK);
  const todo = [...fresh.slice(0, MAX_NEW), ...retry.slice(0, 3), ...recheck].filter((t, i, a) => a.findIndex(x => x.url === t.url) === i);

  let fired = 0;
  for (const t of todo) {
    let html; try { const res = await fetch(t.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } }); if (!res.ok) { errors.push(`${t.slug}: HTTP ${res.status}`); continue; } html = await res.text(); } catch (e) { errors.push(`${t.slug}: ${String(e).slice(0, 100)}`); continue; }
    const a = await analyse(html, t.url, t.slug), rec = tracked[t.url];
    if (!rec) note("detected", `New PRC article: ${t.slug}`);
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
  for (const m of errors) note("error", m);
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

// One scheduled run: article watcher, then the official schedule refresh, then save the event log once.
async function run(env) {
  const ev = []; EV = ev;
  try { await detect(env); } catch (e) { note("error", "Watcher crashed: " + String(e).slice(0, 200)); console.log("detect failed:", String(e)); }
  try {
    const r = await refreshOfficialReleaseSchedule({ sources: SCHEDULE_SOURCES, kv: env.KV, now: new Date() });
    if (r.status === "updated" || r.status === "updated_with_unparsed_rows") {
      const n = r.snapshot.nearest;
      note("info", `PRC schedule updated: ${r.snapshot.upcoming_count} upcoming, nearest ${n ? n.exam + " on " + n.target_release_date : "none"}${r.snapshot.unparsed_count ? `, ${r.snapshot.unparsed_count} unreadable dates` : ""}.`);
    } else if (r.status !== "cached") {
      note("warning", `PRC schedule check: ${r.status}${r.error ? " - " + r.error : ""}`);
      console.log("schedule:", r.status, r.error || "");
    }
  } catch (e) { note("error", "Schedule refresh crashed: " + String(e).slice(0, 200)); }
  try { await recordEvents(env, ev); } catch (e) { console.log("event log failed:", String(e)); }
  EV = null;
}

// GET /status  -> what the owner dashboard (owner.html) reads: { updated, events:[{t,type,msg}] }
async function status(req, env) {
  let origin = "*"; try { origin = new URL(env.SITE_URL).origin; } catch {}
  const headers = { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": origin, "access-control-allow-methods": "GET, OPTIONS", "access-control-allow-headers": "content-type", "cache-control": "no-store", vary: "Origin" };
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers });
  const j = async k => { try { return JSON.parse((await env.KV.get(k)) || "null"); } catch { return null; } };
  const [events, last_run, snap] = await Promise.all([j("events"), j("last_run"), j(RELEASE_SCHEDULE_CACHE_KEY)]);
  const list = Array.isArray(events) && events.length ? events : [{ t: Date.now(), type: "info", msg: "Watcher is running. No events recorded yet." }];
  return new Response(JSON.stringify({
    updated: Date.now(), events: list, last_run,
    schedule: snap ? { fetched_at: snap.fetched_at, upcoming_count: snap.upcoming_count, nearest: snap.nearest } : null
  }), { headers });
}

export default {
  scheduled(_e, env, ctx) { ctx.waitUntil(run(env)); },
  async fetch(req, env) {
    const p = new URL(req.url).pathname;
    if (p === "/status") return status(req, env);
    if (p === "/health") return new Response(JSON.stringify({ last_run: JSON.parse((await env.KV.get("last_run")) || "null"), tracked: Object.keys(JSON.parse((await env.KV.get("tracked")) || "{}")).length }), { headers: { "content-type": "application/json" } });   // no secrets, just watcher status
    if (p === "/api/releases/upcoming") return getReleaseScheduleResponse(req, { PEAK_WEEK: env.KV });   // schedule snapshot lives in KV
    return p.startsWith("/owner") ? owner(req, env) : new Response("ok");
  },
};
