# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)

## Current Version: 1.6.0

12 routers, 70+ endpoints, optimization engine operational, 2 active Meta campaigns syncing real performance data.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy (from any machine with API access)
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
# App auto-restarts after pulling. No manual Republish needed.

# GitHub webhook auto-deploy (configure in repo Settings > Webhooks)
# URL: https://auto-sem.replit.app/api/v1/deploy/github-webhook
# Content-Type: application/json
# Set GITHUB_WEBHOOK_SECRET env var for signature verification

# Swagger docs
https://auto-sem.replit.app/docs
```

No test framework configured. Use Swagger UI or curl for testing.

## Architecture

**FastAPI** app (`main.py`) with 12 routers under `/api/v1/`:

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
| `klaviyo` | `/klaviyo` | Klaviyo flows, abandoned cart, email marketing |
| `health` | `/health` | Deep health check — DB, tokens, scheduler, financials |
| `automation` | - | Activity log endpoint (merged into dashboard router) |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)
Tables: products, campaigns, meta_tokens, tiktok_tokens, activity_logs, settings

**Scheduler** (`scheduler.py`): APScheduler runs:
- Performance sync every 2 hours
- Optimization every 6 hours
- Shopify token refresh every 20 hours

## Key Files

- `main.py` — FastAPI app factory, router registration, version
- `app/version.py` — Single source of truth for VERSION
- `app/routers/` — All 12 API router modules
- `app/services/meta_ads.py` — Meta API with appsecret_proof, adset discovery
- `app/services/optimizer.py` — Auto-actions: budget scaling, pausing, CPC rules
- `app/services/klaviyo_service.py` — Abandoned cart flow, Shopify discount codes
- `app/services/shopify_token.py` — Centralized token manager with DB persistence
- `app/services/shopify_webhook_register.py` — Webhook registration with logging
- `app/services/attribution.py` — UTM-based revenue attribution from Shopify webhooks
- `app/database.py` — SQLAlchemy models and session management
- `app/schemas.py` — Pydantic request/response models
- `scheduler.py` — Background task scheduling
- `templates/dashboard.html` — Dashboard UI with 7 tabs

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
- This blocks: webhook registration (orders/create), revenue attribution from real orders
- Fix: Update app scopes in Shopify dev dashboard, then reinstall
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
- **NEEDS FIX:** Add DB fallback in KlaviyoService or debug Replit Secrets loading
- 3-email abandoned cart flow ready to deploy once key loads

### Google Ads
- Router exists but returns `not_configured` (no credentials set)
- Phase 2+ integration planned

## Deploy Flow

```
1. Claude Code pushes to GitHub
2. Chat Claude calls POST /api/v1/deploy/pull with X-Deploy-Key header
3. App auto-pulls from GitHub and restarts (os.execv)
4. No manual Republish needed
```

If auto-restart fails, manual deploy:
```bash
# In Replit shell:
git fetch github main && git reset --hard github/main
# Then Republish in Replit UI
```

## Known Bugs

### BUG-1: Scheduler optimizer missing DB session
The scheduler's automation cycle fails with: `CampaignOptimizer.__init__() missing 1 required positional argument: 'db'`
The optimizer works when called via API but the scheduler doesn't pass the DB session.
**Fix needed in:** `scheduler.py` — create a DB session and pass to CampaignOptimizer

### BUG-2: Klaviyo env var not loading
`KLAVIYO_API_KEY` is in Replit Secrets but `os.environ.get("KLAVIYO_API_KEY")` returns empty.
**Fix needed:** Add DB fallback — check SettingsModel if env var is empty. Add POST /klaviyo/set-key endpoint.

### BUG-3: Shopify scopes insufficient
Current scopes lack orders and webhooks. The `orders/create` webhook topic is rejected.
**Fix needed:** Update app scopes in Shopify dev dashboard to include read_orders, write_orders, read_webhooks, write_webhooks.

## Dashboard Tabs

1. **Overview** — KPIs, optimization progress bars, product/collection counts
2. **Meta Ads** — Campaign table with spend/clicks/CTR/CPC/ROAS, budget controls, sync button
3. **Klaviyo** — Email marketing status (pending key configuration)
4. **Shopify** — Store connection, products, token TTL
5. **SEO & Content** — Blog posts, technical SEO status
6. **System Health** — Service status, activity log, scheduler, financials
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
- Deploy via API — never require manual Republish
