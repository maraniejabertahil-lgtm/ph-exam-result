const USER_AGENT = "PH-EXAM-RESULTS-Watcher";
export const RELEASE_SCHEDULE_CACHE_KEY = "official-release-schedule:v1";
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

export function parsePrcScheduleHtml(html, sourceUrl, now = new Date()) {
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

export function discoverSchedulePageUrls(indexHtml, indexUrl, now = new Date(), maxPages = 2) {
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

export function robotsAllowsPath(robotsText, path, userAgent = "PH-EXAM-RESULTS-Watcher") {
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

export async function refreshOfficialReleaseSchedule({ sources, kv, fetchImpl = fetch, now = new Date() }) {
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

export async function getReleaseScheduleResponse(request, env) {
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
