// FREE-plan friendly: no PDF work here (10 ms CPU limit). It only spots new PRC articles and wakes GitHub Actions.
const M = "january|february|march|april|may|june|july|august|september|october|november|december";
const MM = `(?:${M})(?:-(?:and|to)-(?:${M}))*`;
const RESULT = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(result|released)`);
const SCHED = new RegExp(`^${MM}-20\\d\\d-.*licen[sc]ure.*(schedule|room-assignment)`);

async function detect(env) {
  const raw = await env.KV.get("seen"), firstRun = raw === null;   // first run only records what already exists (no old-result spam)
  const seen = JSON.parse(raw || "[]"), fresh = [];
  const w = (env.WATCH || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
  for (const page of [0, 1]) {
    let html; try { html = await (await fetch(`https://prc.gov.ph/articles?page=${page}`, { headers: { "User-Agent": "Mozilla/5.0 (compatible; PHExamResultBot/1.0)" } })).text(); } catch { continue; }
    for (const m of html.matchAll(/href=["']([^"'#?]*\/article\/([a-z0-9-]+))["']/g)) {
      const [, path, slug] = m, url = new URL(path, "https://prc.gov.ph").href;
      if (seen.includes(url) || fresh.some(f => f.url === url)) continue;
      if (!(RESULT.test(slug) || SCHED.test(slug))) continue;
      if (w.length && !w.some(x => slug.includes(x))) continue;
      fresh.push({ url });
    }
  }
  if (firstRun) { await env.KV.put("seen", JSON.stringify(fresh.map(f => f.url))); return; }
  for (const f of fresh) {
    const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, { method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "ph-exam-result" },
      body: JSON.stringify({ event_type: "prc", client_payload: { url: f.url, detected_at: Date.now() } }) });
    if (r.status === 204) seen.push(f.url);          // only mark seen when GitHub accepted it (else retried next minute)
  }
  if (fresh.length) await env.KV.put("seen", JSON.stringify(seen.slice(-400)));
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
  fetch(req, env) { return new URL(req.url).pathname.startsWith("/owner") ? owner(req, env) : new Response("ok"); },
};
