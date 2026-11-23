// PH EXAM RESULT watcher - single self-contained Worker file (no imports).
// Part 1: official PRC future-release schedule reader.  Part 2: article watcher, /status, /api/releases/upcoming, owner login.

// ======== PART 1: PRC schedule reader ========
const USER_AGENT = "PH-EXAM-RESULTS-Watcher";
const RELEASE_SCHEDULE_CACHE_KEY = "official-release-schedule:v1";
const REFRESH_INTERVAL_MS = 25 * 60 * 1000;          // 25 min guard — fires on every 30-min cron slot
const MAX_PUBLIC_SNAPSHOT_AGE_MS = 40 * 60 * 1000;   // 40 min tolerance — covers one missed 30-min refresh slot
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

// "November 19 and 20, 2026" -> { month: "November", year: "2026" }. Only the first month is used.
// A date range that crosses a month ("November 28 to December 5, 2026") gives the month it starts in.
function parseExamMonth(value, fallbackYear) {
  const text = cleanText(value);
  const m = new RegExp("\\b(" + MON_WORDS + ")\\b", "i").exec(text);
  if (!m) return null;
  const y = /\b(20\d{2})\b/.exec(text);
  const year = y ? y[1] : (fallbackYear ? String(fallbackYear) : "");
  if (!year) return null;
  const name = m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase();
  return { month: name, year };
}
const MON_WORDS = "January|February|March|April|May|June|July|August|September|October|November|December";

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
    let examIndex = -1;

    for (let index = 0; index < rows.length; index += 1) {
      const cells = parseCells(rows[index]);
      const name = headerColumn(cells, (text) => text.includes("NAME OF EXAMINATION"));
      const release = headerColumn(cells, (text) => text.includes("TARGET DATE") && text.includes("RELEASE"));
      // The "DATE/S OF EXAMINATION" column. Optional: if PRC's table has no such column, the release month is used instead.
      const examDate = headerColumn(cells, (text) => text.includes("DATE") && text.includes("EXAM")
        && !/RELEASE|TARGET|RESULT|APPLICATION|DEADLINE|OPENING/.test(text));
      if (name >= 0 && release >= 0) {
        headerRowIndex = index;
        nameIndex = name;
        releaseIndex = release;
        examIndex = examDate;
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
      const examWhen = examIndex >= 0 && examIndex !== nameIndex && examIndex !== releaseIndex
        ? parseExamMonth(cells[examIndex]?.text || "", scheduleYear) : null;
      parsedRows.push({
        authority: "PRC",
        exam,
        schedule_year: scheduleYear,
        target_release_date: date,
        target_release_label: rawDate,
        ...(examWhen ? { exam_month: examWhen.month, exam_year: examWhen.year } : {}),
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

    // Save only when the expected dates changed (exam name + date). Days-left counts are ignored.
    const listKey = (list) => (Array.isArray(list) ? list : []).map((i) => i.exam + "|" + i.target_release_date + "|" + (i.exam_month || "") + (i.exam_year || "")).join("\n");
    if (cached && listKey(cached.upcoming) === listKey(upcoming)) {
      return { status: "unchanged", snapshot: cached };
    }

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
    // Always show the last saved schedule. No age check.
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

// SCHEDULE_CRON must match the cron string in wrangler.toml exactly — Cloudflare passes event.cron
// as the literal string from the config, so a mismatch means the schedule task never runs.
const SCHEDULE_CRON = "0 */2 * * *";

const SCHEDULE_SOURCES = [{
  id: "PRC-OFFICIAL-SCHEDULE-INDEX", authority: "PRC", source_type: "official_schedule_index",
  enabled: true, authorized: true, url: "https://www.prc.gov.ph/exam-schedules-menu",
  max_schedule_pages: 2, refresh_interval_minutes: 25   // must be < 30 so the 30-min cron slot always refreshes
}];

// =====================================================================================================
//  LINK KEYWORDS  <<<  EDIT HERE  >>>
//  These are the exact words PRC prints on its official links, copied from the real PRC article.
//  The Worker finds each link by these words and tells GitHub which link is which:
//      names       = "List of Successful Examinees"       -> needed by pipeline 1 AND pipeline 2
//      schools     = "Performance of Schools"             -> needed by pipeline 2
//      topnotchers = "Successful Examinees who garnered the top 10 highest places"  -> needed by pipeline 2
//  How the matching works:
//    - capital letters and extra spaces do not matter
//    - the link only has to CONTAIN the words (so "List of Successful Examinees for Manila" still counts as names)
//    - if one link matches more than one keyword, the longer (more specific) keyword wins
//  If PRC ever changes a label: keep the old words and ADD the new ones inside the same [ ], in quotes,
//  separated by commas. Example:  names: ["List of Successful Examinees", "List of Passers"],
// =====================================================================================================
const LINK_KEYWORDS = {
  names: ["List of Successful Examinees"],
  schools: ["Performance of Schools"],
  topnotchers: ["Successful Examinees who garnered the top 10 highest places"],
};

const MON = "january|february|march|april|may|june|july|august|september|october|november|december";
const MM = `(?:${MON})(?:-(?:and|to)-(?:${MON}))*`;
const RESULT = new RegExp(`^${MM}-20\\d\\d-.*(licen[sc]ure|examination).*(result|released)`);
const SCHED = new RegExp(`^${MM}-20\\d\\d-.*(licen[sc]ure|examination).*(schedule|room-assignment)`);
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

// ---- Link keywords: which official link is this? ----
const squash = s => decodeEntities(String(s || "")).replace(/\s+/g, " ").trim().toLowerCase();

// Returns { kind, keyword } for the best-matching keyword in LINK_KEYWORDS, or null if the link is none of the three.
function matchLink(text) {
  const t = squash(text);
  let best = null;
  for (const [kind, words] of Object.entries(LINK_KEYWORDS)) {
    for (const w of words) {
      const k = squash(w);
      if (k && t.includes(k) && (!best || k.length > best.keyword.length)) best = { kind, keyword: k };
    }
  }
  return best;
}

// What is left of a "names" link's words after the keyword, e.g. "List of Successful Examinees for Manila" -> "Manila".
// Several lists in one article are told apart by this label. A plain "List of Successful Examinees" gives "".
function labelOf(text, keyword) {
  const clean = decodeEntities(text).replace(/\s+/g, " ").trim();
  const at = clean.toLowerCase().indexOf(keyword);
  if (at < 0) return "";
  const trim = s => s.replace(/^[\s\-:,]+|[\s\-:,]+$/g, "");
  let rest = clean.slice(at + keyword.length).replace(/^\s*(?:examinees?|passers?|candidates?)\b/i, "");
  rest = trim(rest).replace(/^(?:for|of|in)\s+/i, "");
  return trim(rest);
}

// Pull every fact we care about out of one PRC article page.
async function analyse(html, url, slug) {
  html = html.slice(0, 200000);
  const title = ((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || "").split("|")[0].replace(/\s+/g, " ").trim();
  const pub = (html.match(/(?:article:published_time|datePublished)["'][^>]*content=["']([^"']+)/i)
    || html.match(/content=["']([^"']+)["'][^>]*property=["']article:published_time/i)
    || html.match(/<time[^>]*datetime=["']([^"']+)/i) || [])[1] || null;
  const links = [];
  for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#]+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const text = m[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    let abs;
    try { abs = new URL(m[1], url).href; } catch { continue; }
    // Keep only the official list links: their words match LINK_KEYWORDS above,
    // or the address is a Google Drive file. Privacy notices, forms and other PDFs are ignored.
    const hit = matchLink(text);
    if (!hit && !/drive\.google\.com|docs\.google\.com/i.test(abs)) continue;
    const entry = { text: text.slice(0, 120), href: abs, kind: hit ? hit.kind : null };
    if (hit && hit.kind === "names") entry.label = labelOf(text, hit.keyword);
    const same = links.find(l => l.href === abs);
    if (same) { if (!same.kind && hit) Object.assign(same, entry); continue; }   // same address twice: keep the one that has a kind
    if (hit || links.length < 20) links.push(entry);
  }
  const text = html.replace(/<(script|style|head|title)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
  const posted = (text.match(POSTED_RE) || [])[1] || pub;
  const sentences = text.split(/(?<=[.!?])\s+/).filter(s => s.length < 400 && /releas|post|publish|available|announc|resched|postpon|delay/i.test(s) && (DATE_RE.test(s) || WITHIN_RE.test(s))).slice(0, 5);
  const dateHit = sentences.map(s => s.match(DATE_RE)).find(Boolean), within = sentences.map(s => s.match(WITHIN_RE)).find(Boolean);
  const delayed = DELAY.test(title) || sentences.some(s => DELAY.test(s));
  const isResult = RESULT.test(slug) || links.some(l => l.kind === "names");
  const info = {
    title, published_at: posted, release_date: dateHit ? toISO(dateHit[0]) : null, release_date_text: dateHit ? dateHit[0] : null,
    release_within: within ? within[0] : null, status: delayed ? "delayed" : (isResult ? "released" : "scheduled"),
    note: sentences[0] || null, links,
    counts: [...text.matchAll(/([\d,]+)\s+((?:[A-Za-z()'\-]+\s+){0,6}?)out of\s+([\d,]+)/gi)].slice(0, 40).map(m => ({
      passed: Number(m[1].replace(/,/g, "")), total: Number(m[3].replace(/,/g, "")), ctx: m[0],
      after: text.slice(m.index + m[0].length, m.index + m[0].length + 30).toLowerCase()
    })),
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

// How many official "list of successful examinees" (kind "names") links does this article carry right now?
const listCount = info => (info.links || []).filter(l => l.kind === "names").length;
// PRC sometimes posts a result article before it attaches the official list. GitHub can no longer read PRC,
// so the Worker waits here (checking again every minute) and sends the alert the moment the list link appears.
const WAIT_LIST_MS = 6 * 3600e3;

// ---- Late links ----
// PRC sometimes adds "Performance of Schools" and/or the top 10 link AFTER the list of successful examinees.
// The first alert (event "prc") has already gone out, so the Worker remembers which links it has sent (rec.lk)
// and, when a new schools / top-10 link shows up, sends one small extra alert (event "prc-links") to GitHub.
// That alert wakes only the add-links workflow, which captures just those pages. It never reads the names again.
const EXTRA_KINDS = ["schools", "topnotchers"];
const linkKeys = info => (info.links || []).filter(l => l.kind).map(l => l.href);
const extraLinks = info => (info.links || []).filter(l => EXTRA_KINDS.includes(l.kind));

async function fireLinks(env, repo, url, info) {
  const pick = kind => (extraLinks(info).find(l => l.kind === kind) || {}).href || "";
  const payload = { url, title: info.title || "", schools_url: pick("schools"), topnotchers_url: pick("topnotchers"), detected_at: Date.now() };
  let out;
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, { method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "ph-exam-result", "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ event_type: "prc-links", client_payload: payload }) });
    out = { ok: r.status === 204, status: r.status, body: r.status === 204 ? "" : (await r.text()).slice(0, 200) };
  } catch (e) { out = { ok: false, status: 0, body: String(e).slice(0, 200) }; }
  const what = `late links (${[payload.schools_url && "schools", payload.topnotchers_url && "top 10"].filter(Boolean).join(" + ")}) ${url.split("/").pop()}`;
  note(out.ok ? "dispatched" : "error", out.ok ? `Sent to GitHub: ${what}` : `GitHub dispatch failed, HTTP ${out.status}: ${what}`);
  return out;
}

async function detect(env) {
  const MAX_DISPATCH_TRIES = 5;
  const OLD_ARTICLE_MS = 7 * 864e5;   // articles published longer ago than this are recorded silently, never alerted
  const now = Date.now(), minute = Math.floor(now / 60000), errors = [], repo = repoOf(env.GITHUB_REPO);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) errors.push(`GITHUB_REPO must look like owner/repo (got "${env.GITHUB_REPO}")`);
  const rawT = await env.KV.get("tracked"), rawS = await env.KV.get("seen");
  const firstRun = rawT === null && rawS === null;
  const tracked = JSON.parse(rawT || "{}"); let dirty = false, fired = 0;
  for (const u of JSON.parse(rawS || "[]")) if (!tracked[u]) { tracked[u] = { slug: u.split("/").pop(), first: now, hash: null, sent: true }; dirty = true; }
  const w = (env.WATCH || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);

  // 1) Read the PRC exam-results listing pages (reads only, no KV writes here).
  const found = [];
  const LISTING_HOSTS = ["https://prc.gov.ph", "https://www.prc.gov.ph"];
  for (const page of [0, 1]) {
    let html = null;
    for (const host of LISTING_HOSTS) {
      try {
        const res = await fetch(`${host}/articles/exam-results?page=${page}`, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } });
        if (!res.ok) continue;
        html = await res.text();
        break;
      } catch { /* try the next host */ }
    }
    if (html === null) { errors.push(`prc.gov.ph exam-results page ${page}: unreachable`); continue; }
    for (const m of html.matchAll(/<a\b[^>]*href=["']([^"'#?]*\/article\/([a-z0-9-]+))["'][^>]*>([\s\S]*?)<\/a>/gi)) {
      const articleUrl = new URL(m[1], "https://prc.gov.ph");
      articleUrl.hostname = "prc.gov.ph"; // Normalize discovered article links to the non-www host.
      const url = articleUrl.href, slug = m[2], label = m[3].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().toLowerCase(), hay = `${slug} ${label}`;
      if (found.some(f => f.url === url)) continue;
      if (!(RESULT.test(slug) || SCHED.test(slug) || (ABOUT_EXAM.test(hay) && ABOUT_NEWS.test(hay)))) continue;
      if (w.length && !w.some(x => hay.includes(x))) continue;
      found.push({ url, slug });
    }
  }

  // 2) First run: remember what already exists, so no old alerts are sent.
  if (firstRun) {
    for (const f of found) tracked[f.url] = { slug: f.slug, first: now, hash: null, sent: true };
    note("info", `First run: remembered ${found.length} existing PRC articles (no alerts sent for old ones).`);
    await env.KV.put("tracked", JSON.stringify(tracked));
    return;
  }

  // 3) Decide which articles to open this run.
  const fresh = found.filter(f => !tracked[f.url])
    .sort((a, b) => Number(RESULT.test(b.slug)) - Number(RESULT.test(a.slug)));
  const waiting = Object.entries(tracked).filter(([, r]) => r.sent === "waiting").map(([url, r]) => ({ url, slug: r.slug }));
  const retry = Object.entries(tracked).filter(([, r]) => r.sent === false).map(([url, r]) => ({ url, slug: r.slug }))
    .sort((a, b) => Number(RESULT.test(b.slug)) - Number(RESULT.test(a.slug)));
  const recheck = Object.entries(tracked).filter(([u, r]) => r.sent === true && now - r.first < FRESH_DAYS * 864e5 && (minute + sum(u)) % RECHECK_EVERY === 0)
    .map(([url, r]) => ({ url, slug: r.slug })).slice(0, MAX_RECHECK);
  const todo = [...fresh.slice(0, MAX_NEW), ...waiting.slice(0, 3), ...retry.slice(0, 3), ...recheck].filter((t, i, a) => a.findIndex(x => x.url === t.url) === i);

  // 4) Open each article and act only on real changes.
  for (const t of todo) {
    let html;
    try {
      const res = await fetch(t.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } });
      if (!res.ok) continue;
      html = await res.text();
    } catch { continue; }
    const a = await analyse(html, t.url, t.slug), rec = tracked[t.url];

    if (!rec) {
      const publishedMs = Date.parse(a.info.published_at || "");
      if (Number.isFinite(publishedMs) && now - publishedMs > OLD_ARTICLE_MS) {
        // Old article we have never seen: remember it silently.
        note("info", `Old article seen for the first time, no alert: ${t.slug}`);
        tracked[t.url] = { slug: t.slug, first: now, hash: a.hash, sent: true, kind: a.kind, release: a.info.release_date, status: a.info.status, lk: linkKeys(a.info) };
        dirty = true;
        continue;
      }
      if (a.kind === "result" && listCount(a.info) === 0) {
        // A result article whose official list is not attached yet: do NOT start a run that would fail. Wait for the list.
        note("info", `Result article found, official list not attached yet. Waiting: ${t.slug}`);
        tracked[t.url] = { slug: t.slug, first: now, hash: a.hash, sent: "waiting", attempts: 0, release: a.info.release_date, status: a.info.status, kind: a.kind };
        dirty = true;
      } else {
        // Brand-new article: send the alert once.
        note("detected", `New PRC article: ${t.slug}`);
        const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
        tracked[t.url] = { slug: t.slug, first: now, hash: a.hash, sent: r.ok, attempts: r.ok ? 0 : 1, release: a.info.release_date, status: a.info.status, kind: a.kind, lk: linkKeys(a.info) };
        dirty = true;
        if (r.ok) fired++;
      }

    } else if (rec.sent === "waiting") {
      if (a.kind === "result" && listCount(a.info) > 0) {
        // The official list link is now on the article: send the alert (a failed send is retried by the branch below).
        note("detected", `Official list is now attached: ${t.slug}`);
        const r = await fire(env, repo, t.url, a.kind, a.info, { change: "new" });
        Object.assign(rec, { sent: r.ok ? true : false, attempts: r.ok ? 0 : 1, hash: a.hash, release: a.info.release_date, status: a.info.status, kind: a.kind, lk: linkKeys(a.info) });
        dirty = true;
        if (r.ok) fired++;
      } else if (now - rec.first > WAIT_LIST_MS) {
        rec.sent = "gave_up";
        note("gave_up", `No official list appeared within 6 hours: ${t.slug}`);
        dirty = true;
      }

    } else if (rec.sent === false) {
      // Earlier alert failed: retry, but stop after MAX_DISPATCH_TRIES.
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "retry" });
      const attempts = (rec.attempts || 0) + 1;
      const giveUp = !r.ok && attempts >= MAX_DISPATCH_TRIES;
      Object.assign(rec, { sent: r.ok ? true : (giveUp ? "gave_up" : false), attempts, release: a.info.release_date, status: a.info.status, kind: a.kind, lk: linkKeys(a.info) });
      if (giveUp) note("gave_up", `Stopped retrying alert for ${t.slug} after ${attempts} tries.`);
      dirty = true;
      if (r.ok) fired++;

    } else if (rec.hash === null) {
      // Old article seen for the first time: record its baseline, no alert.
      Object.assign(rec, { hash: a.hash, release: a.info.release_date, status: a.info.status, kind: a.kind, lk: linkKeys(a.info) });
      dirty = true;

    } else if (a.kind === "result" && rec.kind === "announcement") {
      // A known announcement has now become a real result: send one "released" alert.
      const r = await fire(env, repo, t.url, a.kind, a.info, { change: "released", previous_release_date: rec.release || null });
      if (r.ok) { Object.assign(rec, { kind: "result", hash: a.hash, release: a.info.release_date, status: a.info.status, lk: linkKeys(a.info) }); dirty = true; fired++; }

    } else if (a.kind === "announcement" && (a.info.release_date !== rec.release || a.info.status !== rec.status)) {
      // The expected date or delay status really changed: send one alert.
      const change = a.info.status === "delayed" && rec.status !== "delayed" ? "delayed" : (a.info.release_date !== rec.release ? "date-changed" : "updated");
      const r = await fire(env, repo, t.url, a.kind, a.info, { change, previous_release_date: rec.release || null });
      if (r.ok) { Object.assign(rec, { kind: "announcement", release: a.info.release_date, status: a.info.status }); dirty = true; fired++; }

    } else if (a.kind === "result" && rec.kind === "result" && rec.sent === true) {
      // Late links: a result we already sent. Did PRC add a schools or top-10 link since?
      if (!Array.isArray(rec.lk)) {
        // Record from before this feature existed: remember its links, send nothing.
        rec.lk = linkKeys(a.info);
        dirty = true;
      } else {
        const added = extraLinks(a.info).filter(l => !rec.lk.includes(l.href));
        if (added.length) {
          note("detected", `New link(s) on an article already sent (${added.map(l => l.kind).join(" + ")}): ${t.slug}`);
          const r = await fireLinks(env, repo, t.url, a.info);
          rec.lkTries = (rec.lkTries || 0) + 1;
          if (r.ok || rec.lkTries >= MAX_DISPATCH_TRIES) {
            if (!r.ok) note("gave_up", `Stopped sending late links for ${t.slug} after ${rec.lkTries} tries.`);
            rec.lk = linkKeys(a.info);
            delete rec.lkTries;
          }
          dirty = true;
          if (r.ok) fired++;
        }
      }
    }

    if (a.kind === "result") { try { await reportReleased(env, t.url, t.slug, a.info); } catch { /* ignore */ } }
  }

  // 5) Save the tracked list only when something real changed.
  if (dirty) {
    const keep = Object.entries(tracked).sort((x, y) => y[1].first - x[1].first).slice(0, 150);
    await env.KV.put("tracked", JSON.stringify(Object.fromEntries(keep)));
  }
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

// ======== PART 3: Article Watcher -> Schedule Watcher -> ring (upcoming.py) ========
const RELEASED_KEY = "released-schedule:v1";
const UPCOMING_STATUS_KEY = "upcoming-status:v1";
const RELEASE_MATCH_DAYS = 45;
const DAY_MS = 86400000;
const MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];

const normName = s => String(s || "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
const targetMs = iso => Date.parse(iso + "T00:00:00Z");

async function readJsonKey(env, key, fallback) {
  try { return JSON.parse((await env.KV.get(key)) || "null") ?? fallback; } catch { return fallback; }
}

// Article Watcher calls this after it reads a RESULT article.
// It records which scheduled release date that result completes, then asks the schedule side to recompute.
async function reportReleased(env, articleUrl, slug, info) {
  const released = await readJsonKey(env, RELEASED_KEY, []);
  if (released.some(r => r.article_url === articleUrl)) return;   // already reported
  const snap = await readJsonKey(env, RELEASE_SCHEDULE_CACHE_KEY, null);
  const items = Array.isArray(snap?.upcoming) ? snap.upcoming : [];
  const publishedMs = Date.parse(info.published_at || "") || Date.now();
  const hay = normName(`${info.title || ""} ${slug}`);
  let best = null, bestGap = Infinity;
  for (const it of items) {
    const name = normName(String(it.exam || "").replace(/\([^)]*\)/g, " "));
    if (!name || !hay.includes(name)) continue;
    const gap = Math.abs(targetMs(it.target_release_date) - publishedMs) / DAY_MS;
    if (gap <= RELEASE_MATCH_DAYS && gap < bestGap) { best = it; bestGap = gap; }
  }
  if (!best) return;   // not a scheduled exam, nothing to report
  const my = (info.title || "").match(/\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)\b/i);
  released.unshift({
    exam: best.exam, target_release_date: best.target_release_date,
    month: my ? my[1] : "", year: my ? my[2] : "",
    released_on: new Date(publishedMs).toISOString(), article_url: articleUrl, slug
  });
  await env.KV.put(RELEASED_KEY, JSON.stringify(released.slice(0, 60)));
  note("info", `Schedule: ${best.exam} (expected ${best.target_release_date}) is released; looking for the next date.`);
  await reconcileSchedule(env);
}

// Schedule side: finds the next expected release that has no result yet, and writes what upcoming.py reads.
async function reconcileSchedule(env) {
  const snap = await readJsonKey(env, RELEASE_SCHEDULE_CACHE_KEY, null);
  if (!snap || !Array.isArray(snap.upcoming)) return;
  const released = await readJsonKey(env, RELEASED_KEY, []);
  const now = Date.now();
  const today = localManilaDate(new Date()).iso;
  const done = it => released.some(r => r.exam === it.exam && r.target_release_date === it.target_release_date);
  const recent = released.filter(r => now - Date.parse(r.released_on) <= 2 * DAY_MS).slice(0, 2).map(r => ({
    exam: r.exam, month: r.month, year: r.year, release_date: r.target_release_date,
    release_text: r.target_release_date, published_at: r.released_on, slug: r.slug
  }));
  const next = snap.upcoming.filter(it => it.target_release_date >= today && !done(it)).slice(0, 2).map(it => {
    const d = new Date(targetMs(it.target_release_date));
    return {
      exam: it.exam, month: MONTH_NAMES[d.getUTCMonth()], year: String(d.getUTCFullYear()),
      exam_month: it.exam_month || "", exam_year: it.exam_year || "",
      release_date: it.target_release_date, release_text: it.target_release_label || it.target_release_date,
      published_at: null, slug: ""
    };
  });
  const upcoming = [...recent, ...next];
  const prev = await readJsonKey(env, UPCOMING_STATUS_KEY, null);
  if (JSON.stringify(prev?.upcoming) === JSON.stringify(upcoming)) return;   // no change, so no KV write
  await env.KV.put(UPCOMING_STATUS_KEY, JSON.stringify({ upcoming, updated: new Date().toISOString() }));
}

// Pauses for the given milliseconds of wall-clock time, burning zero CPU (pure timer, no computation).
// Used to stagger Pass B by 30 seconds inside a single Worker invocation.
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Runs the schedule refresh on the 30-minute cron.
async function runSchedule(env) {
  const ev = []; EV = ev;
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
  try { await reconcileSchedule(env); } catch (e) { console.log("reconcile failed:", String(e)); }
  try { await recordEvents(env, ev); } catch (e) { console.log("event log failed:", String(e)); }
  EV = null;
}

// Philippines Time helpers: minute of the day in Manila time (0 = 12:00 AM).
function manilaMinuteOfDay(now) {
  const shifted = new Date(now + MANILA_OFFSET_MS);
  return shifted.getUTCHours() * 60 + shifted.getUTCMinutes();
}

// Decides what this minute's trigger should do, in Philippines Time:
//   "both"   = Pass A, wait 30 seconds, Pass B
//   "pass_a" = Pass A only
//   "off"    = do nothing
function watchPlan(now = Date.now()) {
  const m = manilaMinuteOfDay(now);
  if (m >= 150 && m < 320) return "off";                                              // 2:30 AM to 5:20 AM: shutdown
  if (m >= 320 && m < 405) return Math.floor(now / 60000) % 2 === 0 ? "pass_a" : "off"; // 5:20 AM to 6:45 AM: every 2 min, Pass A only
  if (m >= 120 && m < 150) return "pass_a";                                           // 2:00 AM to 2:30 AM: every 1 min, Pass A only
  return "both";                                                                      // all other hours: Pass A and Pass B
}

async function runWatcher(env) {
  const plan = watchPlan();
  if (plan === "off") return;

  // Pass A
  const evA = []; EV = evA;
  try { await detect(env); } catch (e) { console.log("detect failed A:", String(e)); }
  try { await recordEvents(env, evA); } catch (e) { console.log("event log failed A:", String(e)); }
  EV = null;

  if (plan !== "both") return;

  // Pass B, 30 seconds later
  await sleep(30_000);
  const evB = []; EV = evB;
  try { await detect(env); } catch (e) { console.log("detect failed B:", String(e)); }
  try { await recordEvents(env, evB); } catch (e) { console.log("event log failed B:", String(e)); }
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
  // event.cron is the exact cron string from wrangler.toml.
  // "*/30 * * * *" → runSchedule (release schedule tracker, every 30 min)
  // "* * * * *"    → runWatcher  (exam results watcher, double-pass every 30 s)
  scheduled(event, env, ctx) {
    if (event.cron === SCHEDULE_CRON) {
      ctx.waitUntil(runSchedule(env));
    } else {
      ctx.waitUntil(runWatcher(env));
    }
  },
  async fetch(req, env) {
    const p = new URL(req.url).pathname;
    if (p === "/status") return status(req, env);
    if (p === "/health") return new Response(JSON.stringify({ last_run: JSON.parse((await env.KV.get("last_run")) || "null"), tracked: Object.keys(JSON.parse((await env.KV.get("tracked")) || "{}")).length }), { headers: { "content-type": "application/json" } });   // no secrets, just watcher status
    if (p === "/api/upcoming-status") return new Response((await env.KV.get(UPCOMING_STATUS_KEY)) || '{"upcoming":[]}', { headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*", "cache-control": "no-store" } });
    if (p === "/api/releases/upcoming") return getReleaseScheduleResponse(req, { PEAK_WEEK: env.KV });   // schedule snapshot lives in KV
    return p.startsWith("/owner") ? owner(req, env) : new Response("ok");
  },
};
