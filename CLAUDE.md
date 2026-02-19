# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)

## Current Version: 1.8.0

13 routers, 75+ endpoints. Optimization engine operational with auto-actions. 2 active Meta campaigns syncing real performance data. JSON-LD structured data and XML sitemap generation. Klaviyo with DB key fallback. DB error recovery middleware. Fixed deploy restart mechanism.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy (from any machine with API access)
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
| `dashboard` | `/dashboard` | Aggregated metrics, sync-meta, activity log, emergency controls |
| `meta` | `/meta` | Meta/Facebook OAuth, campaigns, activate/pause/set-budget |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video generation, targeting |
| `campaigns` | `/campaigns` | CRUD for campaign records, /active endpoint |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart |
| `shopify` | `/shopify` | Shopify Admin API, webhook registration, token refresh |
| `google_ads` | `/google` | Google Ads campaigns (returns not_configured when no credentials) |
| `klaviyo` | `/klaviyo` | Klaviyo flows, abandoned cart, email marketing, POST /set-key |
| `health` | `/health` | Deep health check, GET /reset-db for error recovery |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | - | Activity log endpoint (merged into dashboard router) |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)
Tables: products, campaigns, meta_tokens, tiktok_tokens, activity_logs, settings

**Scheduler** (`scheduler.py`): APScheduler runs:
- Performance sync every 2 hours
- Optimization every 6 hours (now with proper DB session — Phase 8 fix)
- Shopify token refresh every 20 hours

## Key Files

- `main.py` — FastAPI app factory, router registration, version
- `app/version.py` — Single source of truth for VERSION
- `app/routers/` — All 13 API router modules
- `app/routers/deploy.py` — Deploy with os._exit(0) restart (Phase 8 fix)
- `app/routers/seo.py` — JSON-LD and sitemap endpoints (Phase 7)
- `app/routers/health.py` — Deep health + GET /reset-db (Phase 8)
- `app/services/meta_ads.py` — Meta API with appsecret_proof, adset discovery
- `app/services/optimizer.py` — Auto-actions: budget scaling, pausing, CPC rules
- `app/services/klaviyo_service.py` — Abandoned cart flow, DB key fallback (Phase 7)
- `app/services/shopify_token.py` — Centralized token manager with DB persistence
- `app/services/shopify_webhook_register.py` — Webhook registration with logging
- `app/services/attribution.py` — UTM-based revenue attribution from Shopify webhooks
- `app/services/jsonld_generator.py` — Product schema.org JSON-LD generator (Phase 7)
- `app/services/sitemap.py` — XML sitemap generator (Phase 7)
- `app/database.py` — SQLAlchemy models, session management, PendingRollbackError recovery (Phase 8)
- `app/schemas.py` — Pydantic request/response models
- `scheduler.py` — Background task scheduling (Phase 8: proper SessionLocal() for optimizer)
- `templates/dashboard.html` — Dashboard UI with 7 tabs (Phase 8: SEO content, auto-refresh log, version display)
- `shopify.app.toml` — Shopify app config with required scopes (Phase 7)

## Active Meta Campaigns

| DB ID | Platform ID | Name | Budget | Status |
|-------|------------|------|--------|--------|
| 114 | 120206746647300364 | Ongoing website promotion | $15/day | ACTIVE |
| 115 | 120241759616260364 | Court Sportswear - Sales - Tennis Apparel | $10/day | ACTIVE |

Ongoing = star performer ($0.11 CPC, 4.9% CTR). Sales = underperforming ($0.73 CPC, 2.8% CTR).

## Optimizer Auto-Actions (Phase 4)

The optimizer runs every 6h and executes real Meta API actions:
- **CPC > $0.50** (landing page flag): Auto-reduce adset budget by 25%
- **CPC > $1.00**: Auto-pause campaign
- **CTR > 3% AND CPC < $0.20**: Auto-increase budget by 20% (capped at $25/day)
- **ROAS < 0.5 after $20+ spend**: Auto-pause campaign
- All actions logged as `AUTO_OPTIMIZE` to ActivityLogModel

## Integrations

### Shopify (Court Sportswear: `4448da-3.myshopify.com`)
- Token: Auto-refreshed via client_credentials every 20h, persisted in SettingsModel
- **MISSING SCOPES:** Current token lacks `read_orders, write_orders, read_webhooks, write_webhooks`
- Scopes were added in Shopify admin but **app needs reinstall** to activate new token permissions
- In Shopify admin: Settings → Apps → Develop apps → AutoSEM → API credentials → click "Install app"
- `shopify.app.toml` (Phase 7) defines correct scopes
- Env vars: `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE`

### Meta Ads (ad account: `act_1358540228396119`, app: `909757658089305`)
- Token stored in DB meta_tokens table
- All API calls require `appsecret_proof` (HMAC-SHA256)
- Env vars: `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`
- `graph.facebook.com` is blocked in Claude's bash — proxy through AutoSEM endpoints

### TikTok Ads
- All campaigns PAUSED (audience targeting broken — 81% gamers, 0% tennis players)
- Do not reactivate until campaigns rebuilt with proper interest targeting
- Env vars: `TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`

### Klaviyo
- API key: `pk_8331b081008957a6922794034954df1d69`
- Stored in Replit Secrets as `KLAVIYO_API_KEY` but env var not loading
- Phase 7 added DB fallback: KlaviyoService checks SettingsModel if env var empty
- Phase 7 added POST /klaviyo/set-key to store key in DB
- Once v1.8.0 is running, set key via: `POST /api/v1/klaviyo/set-key {"api_key": "pk_8331b..."}`
- 3-email abandoned cart flow ready to deploy once key loads

### Google Ads
- Router exists but returns `not_configured` (no credentials set)
- Future integration planned

## Deploy Flow

### ⚠️ CRITICAL REPLIT DEPLOYMENT LESSONS

**Replit Republish/Publish wipes the .git directory.** Every time you Republish, it creates a fresh deployment container. Any previous `deploy/pull` that initialized .git is lost.

**Correct deploy sequence:**
```
1. Claude Code pushes to GitHub
2. Chat Claude calls POST /api/v1/deploy/pull (initializes .git if needed, pulls code)
3. v1.8.0+ uses os._exit(0) with 2s delay — Replit's supervisor should auto-restart
4. If auto-restart works → done, verify via /health
5. If auto-restart fails → user must Republish in Replit UI
```

**After Republish, you MUST re-pull:**
```
Republish → fresh container (no .git, old code baked in from workspace)
→ POST /deploy/pull again → initializes .git, fetches latest from GitHub
→ Restart happens → now running latest code
```

**Alternative: Use Replit Agent to deploy:**
The Replit Agent can clone from GitHub and copy files into the workspace directly:
```
1. git clone https://github.com/Dennisdeuce/AutoSEM.git /tmp/autosem-fresh
2. rsync -av --exclude='.git' /tmp/autosem-fresh/ ./
3. Kill/restart the process OR click Publish in Replit UI
```
This bypasses the deploy/pull endpoint entirely and is more reliable when .git state is broken.

**What does NOT work in Replit:**
- `os.execv()` — fails silently, process doesn't restart
- `git fetch` after Republish — .git was wiped, returns errors
- Assuming Republish preserves file state from previous deploys

**What DOES work in Replit (v1.8.0+):**
- `os._exit(0)` via threading.Timer(2s) — Replit's always-on supervisor restarts the process
- `os.kill(os.getpid(), signal.SIGTERM)` as primary, `os._exit(0)` as fallback
- Writing to disk then killing the process
- Replit Agent running shell commands to update code

### Manual fallback deploy:
```bash
# In Replit Shell (NOT the deployed container):
git remote set-url origin https://github.com/Dennisdeuce/AutoSEM.git
git fetch origin main
git reset --hard origin/main
cat app/version.py  # verify version
kill $(pgrep -f "uvicorn main:app")  # Replit auto-restarts
```

## Known Bugs

### BUG-1: Scheduler optimizer missing DB session — FIXED in v1.8.0
~~The scheduler's automation cycle fails with: `CampaignOptimizer.__init__() missing 1 required positional argument: 'db'`~~
Fixed in Phase 8: scheduler.py now creates SessionLocal() and passes to CampaignOptimizer.

### BUG-2: Klaviyo env var not loading — WORKAROUND in v1.7.0+
`KLAVIYO_API_KEY` is in Replit Secrets but `os.environ.get("KLAVIYO_API_KEY")` returns empty.
Workaround: POST /api/v1/klaviyo/set-key stores key in DB. KlaviyoService checks DB fallback.

### BUG-3: Shopify scopes insufficient — PENDING USER ACTION
Current scopes lack orders and webhooks. The `orders/create` webhook topic is rejected.
Scopes added in Shopify admin but **app reinstall required** to activate.
Go to: Settings → Apps → Develop apps → AutoSEM → API credentials → Install app

### BUG-4: Deploy auto-restart — FIXED in v1.8.0
~~os.execv does not work in Replit's managed runtime.~~
Fixed in Phase 8: Uses `os.kill(SIGTERM)` with `os._exit(0)` fallback via 2s timer.
Note: First deploy of v1.8.0 itself required manual Republish (chicken-and-egg).

## Dashboard Tabs

1. **Overview** — KPIs, optimization progress bars, product/collection counts
2. **Meta Ads** — Campaign table with spend/clicks/CTR/CPC/ROAS, budget controls, sync button
3. **Klaviyo** — Email marketing status (pending key configuration)
4. **Shopify** — Store connection, products, token TTL
5. **SEO & Content** — Sitemap link, JSON-LD generation, per-product status (Phase 8)
6. **System Health** — Service status, activity log (auto-refresh 30s, Phase 8), scheduler, financials
7. **Task Tracker** — Optimization tasks and progress

## Environment Variables

See Replit Secrets. Key vars:
`DATABASE_URL`, `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`,
`TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE`, `DEPLOY_KEY`, `KLAVIYO_API_KEY`,
`GITHUB_WEBHOOK_SECRET`

## Key Conventions

- All routers prefixed `/api/v1/<n>`
- Platform tokens stored in DB (meta_tokens, tiktok_tokens tables)
- Shopify token in SettingsModel (auto-refreshed)
- Graceful error handling — endpoints return `{"success": false, "error": "..."}` on failure
- Activity logging via ActivityLogModel for all automated actions
- Meta budget parameters are in **cents** (e.g., 1500 = $15/day)
- DB error recovery: GET /api/v1/health/reset-db clears PendingRollbackError state (Phase 8)
- Deploy via API — pull + auto-restart works in v1.8.0+

## Phase History

- **Phase 1:** Bug fixes, campaign activation, phantom cleanup
- **Phase 2:** Klaviyo service, attribution, health endpoint, dashboard upgrades
- **Phase 3:** Shopify webhooks, schema fixes, Google Ads hardening, scheduler heartbeat (v1.4.0)
- **Phase 4:** Webhook fix, token refresh, optimizer auto-actions, adset discovery (v1.5.0)
- **Phase 5:** Deploy webhook, campaign schema fix, dashboard polish, activity log (v1.6.0)
- **Phase 6:** Auto-restart attempt (os.execv — doesn't work in Replit)
- **Phase 7:** Shopify TOML, Klaviyo DB fallback, JSON-LD, sitemap (v1.7.0)
- **Phase 8:** Deploy restart fix (os._exit), scheduler DB session, dashboard SEO/activity-log/version, DB error recovery (v1.8.0)
