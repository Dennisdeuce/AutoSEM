# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)

## Current Version: 2.0.0

13 routers, 75+ endpoints. Optimizer settings load fixed (key/value store). Phantom campaign cleanup endpoint (DELETE). Manual optimize trigger (POST /dashboard/optimize-now). Klaviyo auto-init from env to DB on every request. Performance sync writes daily_budget from Meta (cents→dollars). Revenue confirmed: $82.98 from 2 orders, 2.05x ROAS (verified via /health/deep). Optimization engine fully operational with CBO-aware budget changes.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy (from Replit Shell — workspace is now a git checkout):
git fetch origin main && git reset --hard origin/main
# Then click "Republish" in Replit Deployments UI

# Alternative deploy via API:
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"

# Swagger docs
https://auto-sem.replit.app/docs
```

No test framework configured. Use Swagger UI or curl for testing.

## Architecture

**FastAPI** app (`main.py`) with 13 routers under `/api/v1/`:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `dashboard` | `/dashboard` | Aggregated metrics, sync-meta, optimize-now, activity log, emergency controls |
| `meta` | `/meta` | Meta/Facebook OAuth, campaigns, activate/pause/set-budget (CBO + adset) |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video generation, targeting |
| `campaigns` | `/campaigns` | CRUD for campaign records, /active, DELETE /cleanup phantom purge |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart |
| `shopify` | `/shopify` | Admin API, webhooks, token refresh, customers, discounts |
| `google_ads` | `/google` | Google Ads campaigns (returns not_configured when no credentials) |
| `klaviyo` | `/klaviyo` | Klaviyo flows, abandoned cart, email marketing, POST /set-key, auto-init from env |
| `health` | `/health` | Deep health check, GET /reset-db for error recovery |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | - | Activity log endpoint (merged into dashboard router) |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)
Tables: products, campaigns, meta_tokens, tiktok_tokens, activity_logs, settings

**Scheduler** (`scheduler.py`): APScheduler runs:
- Performance sync every 2 hours
- Optimization every 6 hours (with proper DB session — Phase 8 fix)
- Shopify token refresh every 20 hours

## Key Files

- `main.py` — FastAPI app factory, router registration, version
- `app/version.py` — Single source of truth for VERSION
- `app/routers/` — All 13 API router modules
- `app/routers/meta.py` — CBO-aware budget updates (try campaign-level first, fallback to adset)
- `app/routers/deploy.py` — Deploy with os._exit(0) restart (Phase 8 fix)
- `app/routers/seo.py` — JSON-LD and sitemap endpoints (Phase 7)
- `app/routers/health.py` — Deep health + GET /reset-db (Phase 8)
- `app/routers/shopify.py` — Webhooks, customers, discounts, order webhook handler (Phase 9)
- `app/services/meta_ads.py` — Meta API with appsecret_proof, adset discovery
- `app/services/optimizer.py` — Auto-actions: budget scaling, pausing, CPC rules, key/value settings load (Phase 10 fix)
- `app/services/performance_sync.py` — Meta insights sync, writes all metrics + daily_budget to CampaignModel (Phase 10 fix)
- `app/services/klaviyo_service.py` — Abandoned cart flow, DB key fallback (Phase 7)
- `app/services/shopify_token.py` — Centralized token manager with DB persistence
- `app/services/shopify_webhook_register.py` — Webhook registration with logging
- `app/services/attribution.py` — UTM-based revenue attribution from Shopify webhooks
- `app/services/jsonld_generator.py` — Product schema.org JSON-LD generator (Phase 7)
- `app/services/sitemap.py` — XML sitemap generator (Phase 7)
- `app/database.py` — SQLAlchemy models, session management, PendingRollbackError recovery (Phase 8)
- `app/schemas.py` — Pydantic request/response models
- `scheduler.py` — Background task scheduling (Phase 8: proper SessionLocal() for optimizer)
- `templates/dashboard.html` — Dashboard UI with 7 tabs (Phase 9: revenue display, ROAS cards)
- `shopify.app.toml` — Shopify app config with all required scopes

## Active Meta Campaigns

| DB ID | Platform ID | Name | Budget | Status | Performance |
|-------|------------|------|--------|--------|-------------|
| 114 | 120206746647300364 | Ongoing website promotion | **$20/day** | ACTIVE | $0.11 CPC, 4.75% CTR ⭐ |
| 115 | 120241759616260364 | Court Sportswear - Sales | **$5/day** | ACTIVE | $0.69 CPC, 2.76% CTR |

**Budget shift executed Feb 20:** Moved $5/day from Sales → Ongoing. At Ongoing's $0.11 CPC, the shift = ~45 extra quality clicks/day.

**⚠️ Both campaigns use Campaign Budget Optimization (CBO)** — budget is set at campaign level, not adset level. The `/meta/set-budget` endpoint handles this (tries campaign first, falls back to adset).

**Ad destination URLs:** Ongoing campaign name includes "http://www.court-sportswear.com/" indicating ads point to **homepage**. Should be changed to `/collections/all-mens-t-shirts` for better conversion. No API endpoint currently exists to query/change ad creative destination URLs.

## Optimizer Auto-Actions (Phase 4)

The optimizer runs every 6h and executes real Meta API actions:
- **CPC > $0.50** (landing page flag): Auto-reduce adset budget by 25%
- **CPC > $1.00**: Auto-pause campaign
- **CTR > 3% AND CPC < $0.20**: Auto-increase budget by 20% (capped at $25/day)
- **ROAS < 0.5 after $20+ spend**: Auto-pause campaign
- All actions logged as `AUTO_OPTIMIZE` to ActivityLogModel

### ✅ Optimizer Data Pipeline — FIXED in v2.0.0 (Phase 10)

**Status: Fully operational.** All fixes applied:
1. ✅ PerformanceSyncService writes spend/clicks/impressions/revenue/daily_budget to CampaignModel
2. ✅ Optimizer `_execute_meta_budget_change()` uses CBO-first (campaign-level), adset fallback
3. ✅ Optimizer `_load_settings()` reads key/value SettingsModel correctly (was accessing non-existent columns)
4. ✅ POST /dashboard/optimize-now — manual trigger endpoint
5. ✅ DELETE /campaigns/cleanup — phantom campaign purge (protects known active campaigns)
6. ✅ Klaviyo auto-init: env key written to DB on first /klaviyo/* request
7. ✅ daily_budget synced from Meta API (cents→dollars) during performance sync

**Revenue confirmed:** $82.98 from 2 orders, 2.05x ROAS (verified via /health/deep)

## Integrations

### Shopify (Court Sportswear: `4448da-3.myshopify.com`)
- Token: Auto-refreshed via client_credentials every 20h, persisted in SettingsModel
- **✅ All scopes active** (Phase 9): read_all_orders, write_orders, read_checkouts, read_customers, write_discounts, write_price_rules + existing scopes
- App version "klaviyo2" installed Feb 20, 2026 — token prefix: `shpat_bd9b65...`
- **Webhook registered:** orders/create → `auto-sem.replit.app/api/v1/shopify/webhook/order-created` (ID: 1576353759455)
- **Discount code WELCOME10 created:** price_rule_id 1468723921119, 10% off, once per customer
- Env vars: `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE`

### Meta Ads (ad account: `act_1358540228396119`, app: `909757658089305`)
- Token stored in DB meta_tokens table, 45 days remaining (as of Feb 20)
- All API calls require `appsecret_proof` (HMAC-SHA256)
- CBO budget updates working at campaign level
- Env vars: `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`
- `graph.facebook.com` is blocked in Claude's bash — proxy through AutoSEM endpoints

### TikTok Ads
- All campaigns PAUSED (audience targeting broken — 81% gamers, 0% tennis players)
- Do not reactivate until campaigns rebuilt with proper interest targeting
- Env vars: `TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`

### Klaviyo
- API key: `pk_8331b081008957a6922794034954df1d69`
- ✅ **Auto-init (Phase 10):** On any /klaviyo/* request, key is auto-written from env to DB if missing
- DB fallback via POST /klaviyo/set-key also available for manual override
- 3-email abandoned cart flow ready to deploy once key loads
- **No Klaviyo email capture popup on store** — this is a major gap

### Google Ads
- Router exists but returns `not_configured` (no credentials set)
- Future integration planned

## Court Sportswear Store Audit (Feb 20, 2026)

### CRO Elements Status
- ✅ Free shipping bar in announcement bar + meta description
- ✅ Judge.me reviews installed (extensive config, popup widget, review flow)
- ✅ Meta Pixel active (ID 748250046767709)
- ✅ TikTok Pixel active (CL7OL1BC77U6400CDM60)
- ✅ Google Analytics active (G-ESZRWQZJM5, GTM: GT-MQJ4CVNJ)
- ✅ Google Tag Manager installed
- ✅ Shop Now CTAs present (3 instances)
- ✅ Slideshow/Hero section present
- ✅ Cookie consent (Pandectes GDPR) with Google Consent Mode v2
- ✅ Snapchat Pixel present
- ❌ **Klaviyo email capture: NOT INSTALLED** — no popup, no email collection
- ❌ **Abandoned cart flow: NOT ACTIVE** — Klaviyo key not loaded

### Performance Concerns
- Homepage: 975KB HTML, 0.697s TTFB, **81 script tags**, 219 images
- Collection page: 1.37MB HTML, 1.03s TTFB
- 89% mobile traffic with 57% bounce rate (under 10s)
- Heavy page weight is likely contributing to bounce rate on mobile
- Theme: Shopify "Savor"

### Conversion Funnel Issues
- 67% of traffic lands on homepage (ads point to homepage, not collections)
- Meta ads should deep-link to `/collections/all-mens-t-shirts`
- Zero purchases from 298 landing page views in Feb 1-12 period
- Only 17% of visitors stay longer than 1 minute

## Deploy Flow

### ✅ Workspace Git Checkout (Phase 9 fix)

The Replit workspace is now a direct git checkout. This means `git fetch + reset` in the Replit Shell updates the actual running code.

**Correct deploy sequence (v1.9.0+):**
```bash
# In Replit Shell:
git fetch origin main
git reset --hard origin/main
cat app/version.py  # verify version
# Then click "Republish" in Replit Deployments UI
```

**Why this works now:** Previously, Replit's supervisor restarted from workspace files while deploy/pull wrote to a separate git checkout. Phase 9 fixed this by making the workspace itself the git checkout via:
```bash
git remote set-url origin https://github.com/Dennisdeuce/AutoSEM.git
git fetch origin main
git reset --hard origin/main
```

**The deploy/pull API endpoint still works** but workspace-based deploy is more reliable.

### Previous issues (resolved):
- `os.execv()` doesn't work in Replit
- Republish wipes .git directory (no longer matters since workspace IS the checkout)
- deploy/pull wrote to wrong location (now workspace and deploy target are the same)

## Project Completion Assessment (~70%)

| Component | Status | % |
|-----------|--------|---|
| Platform infrastructure | FastAPI, DB, scheduler, deploy | 90% |
| Meta Ads integration | OAuth, campaigns, sync, budget, pause/activate, CBO | 85% |
| Shopify integration | Token, products, webhooks, discounts, customers | 80% |
| Dashboard | 7 tabs, Meta metrics, SEO, system health, optimize-now | 80% |
| Order tracking/attribution | Webhook registered, handler built, UTM parsing | 70% |
| Optimizer engine | Settings fixed, CBO budget changes, manual trigger, data pipeline working | 85% |
| Performance sync → DB | Writes all metrics + daily_budget to CampaignModel | 85% |
| Klaviyo/email | Router exists, auto-init from env, DB fallback | 35% |
| TikTok integration | OAuth + read-only, no optimization | 25% |
| Google Ads integration | Router exists, no credentials | 15% |
| Automated campaign creation | Service stubs exist, not wired up | 10% |
| Notifications/alerts | Directory exists, no implementation | 5% |

## Known Bugs

### BUG-1: Scheduler optimizer missing DB session — FIXED in v1.8.0

### BUG-2: Klaviyo env var not loading — FIXED in v2.0.0
✅ Auto-init: on any /klaviyo/* request, if key is missing from DB but present in env, it's auto-written to DB. Manual fallback via POST /klaviyo/set-key still available.

### BUG-3: Shopify scopes insufficient — FIXED in v1.9.0
✅ App reinstalled with all required scopes. Token refreshed. Webhook registered.

### BUG-4: Deploy auto-restart — FIXED in v1.8.0 + v1.9.0 workspace fix

### BUG-5: Optimizer data pipeline — FIXED in v2.0.0
✅ PerformanceSyncService now writes all metrics (spend, clicks, impressions, revenue, daily_budget) to CampaignModel. Optimizer settings load fixed to use key/value SettingsModel correctly.

### BUG-6: Optimizer CBO budget changes — FIXED in v1.10.0
✅ Optimizer `_execute_meta_budget_change()` tries campaign-level CBO first, falls back to adset-level.

## Dashboard Tabs

1. **Overview** — KPIs, optimization progress bars, product/collection counts
2. **Meta Ads** — Campaign table with spend/clicks/CTR/CPC/ROAS, revenue column, budget controls, sync button
3. **Klaviyo** — Email marketing status (pending key configuration)
4. **Shopify** — Store connection, products, token TTL
5. **SEO & Content** — Sitemap link, JSON-LD generation, per-product status
6. **System Health** — Service status, activity log (auto-refresh 30s), scheduler, financials
7. **Task Tracker** — Optimization tasks and progress

## Environment Variables

See Replit Secrets. Key vars:
`DATABASE_URL`, `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`,
`TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE`, `DEPLOY_KEY`, `KLAVIYO_API_KEY`,
`GITHUB_WEBHOOK_SECRET`

## Key Conventions

- All routers prefixed `/api/v1/<name>`
- Platform tokens stored in DB (meta_tokens, tiktok_tokens tables)
- Shopify token in SettingsModel (auto-refreshed)
- Graceful error handling — endpoints return `{"success": false, "error": "..."}` on failure
- Activity logging via ActivityLogModel for all automated actions
- Meta budget parameters are in **cents** (e.g., 1500 = $15/day)
- CBO campaigns: set budget at campaign level, not adset level
- DB error recovery: GET /api/v1/health/reset-db clears PendingRollbackError state
- Deploy via workspace git checkout + Republish

## Phase History

- **Phase 1:** Bug fixes, campaign activation, phantom cleanup
- **Phase 2:** Klaviyo service, attribution, health endpoint, dashboard upgrades
- **Phase 3:** Shopify webhooks, schema fixes, Google Ads hardening, scheduler heartbeat (v1.4.0)
- **Phase 4:** Webhook fix, token refresh, optimizer auto-actions, adset discovery (v1.5.0)
- **Phase 5:** Deploy webhook, campaign schema fix, dashboard polish, activity log (v1.6.0)
- **Phase 6:** Auto-restart attempt (os.execv — doesn't work in Replit)
- **Phase 7:** Shopify TOML, Klaviyo DB fallback, JSON-LD, sitemap (v1.7.0)
- **Phase 8:** Deploy restart fix (os._exit), scheduler DB session, dashboard SEO/activity-log/version, DB error recovery (v1.8.0)
- **Phase 9:** Order webhook handler, discount codes (WELCOME10), customer endpoint, revenue dashboard, CBO budget fix, workspace git checkout, Shopify scopes activated (v1.9.0)
- **Phase 10:** Optimizer settings load fix (key/value store), phantom campaign purge (DELETE /cleanup), manual optimize trigger (POST /optimize-now), Klaviyo auto-init env→DB, daily_budget sync from Meta (cents→dollars), version bump to v2.0.0
