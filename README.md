# PH EXAM RESULT, 100% free setup (Cloudflare Free + GitHub Free)

Cloudflare Worker (free cron, every minute) spots a new PRC licensure result/schedule article (ANY exam)
-> wakes GitHub Actions (free) -> reads PRC's official PDF (OCR if scanned), keeps only seq no. + name,
checks count vs PRC's announced total -> builds static pages -> deploys to Cloudflare Pages (free, unlimited traffic)
-> Telegram alert + Facebook Page post with the direct link.

## Setup
1. GitHub: create a PUBLIC repo (unlimited free Actions minutes), upload this folder.
2. Cloudflare Pages project (once):  `npx wrangler pages project create ph-exam-result --production-branch=main`
   then add your custom domain to it (Pages > Custom domains). Put the domain in config.json "site_url".
3. GitHub > Settings > Secrets > Actions: CLOUDFLARE_API_TOKEN (Pages edit), CLOUDFLARE_ACCOUNT_ID,
   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FB_PAGE_TOKEN, FB_PAGE_ID.
4. Worker (free): `cd worker && npx wrangler kv namespace create KV` (paste id in wrangler.toml), edit vars, then
   `npx wrangler secret put GITHUB_TOKEN` (fine-grained token: this repo, Contents write + Metadata),
   `... put SESSION_SECRET` (random), `... put FIREBASE_API_KEY`, then `npx wrangler deploy`.
5. Owner login: Firebase Auth email/password user + Firestore doc `owners/<UID>`; rules:
   match /owners/{uid} { allow read: if request.auth != null && request.auth.uid == uid; allow write: if false; }
   Route phexamresult.com/owner* to the Worker (uncomment routes in wrangler.toml). Passwords stay in Firebase Auth.
6. Analytics: Cloudflare > Web Analytics > add site, paste token in config.json "cf_beacon". Ads later: "adsense_client".
7. Test: GitHub Actions > process-prc-article > Run workflow with a past PRC article URL.

## Speed (honest)
Detect <= 60s (free cron min) + Actions start ~10-30s + read PDF ~10-20s + Pages deploy ~15-30s = about 1.5 to 2.5 min.
Under 1 min needs paid Workers or an always-on free VM polling every 10s. Upgrade later: same code, add polling loop.
## Limits
Built offline/untested on live PRC, Drive, Facebook. Pages: 500 deploys/month free. Layout changes at PRC may need a regex tweak.
