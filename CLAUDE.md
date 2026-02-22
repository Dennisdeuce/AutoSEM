# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)
**Claude Code Tasks:** See `autosem-claude-tasks.md` for 12 revenue-prioritized tasks

## Current Version: 2.5.2 (GitHub)

To deploy: `POST /api/v1/deploy/pull` (updates workspace) → **Republish in Replit Deployments UI** (updates production).

17 routers, 120+ endpoints. Production smoke-tested: 51/54 pass. AI ad copy generation via Claude API (POST /campaigns/generate). Scheduler: midnight CST daily optimization (cron), hourly spend checks, daily performance snapshots, heartbeat ticks. Optimizer awareness-mode fix (won't auto-pause pre-revenue campaigns). Ad-level CRUD fully deployed. Klaviyo hardcoded key removed (BUG-11 fixed). Store health monitor. Meta Pixel auto-installer. Conversion funnel audit. TikTok /campaigns endpoint.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy via API (updates workspace, then Republish for production):
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"

# Swagger docs
https://auto-sem.replit.app/docs
```

No test framework configured. Use Swagger UI or curl for testing.

## 🚨 CRITICAL: Meta Pixel MISSING (Feb 21, 2026)

**The Meta Pixel (fbq) is completely missing from court-sportswear.com.**
- No `fbq()` function call
- No `connect.facebook.net` script
- No `facebook.com/tr` noscript image

**This is the #1 reason for 0 conversions.** Without the pixel, Meta cannot track ANY events (PageView, AddToCart, Purchase). The ad optimization algorithm is flying blind.

### Fix: Run the auto-installer
```bash
# Check current status
curl https://auto-sem.replit.app/api/v1/pixel/status

# Auto-install pixel on Shopify theme
curl -X POST https://auto-sem.replit.app/api/v1/pixel/install

# Verify it's working
curl https://auto-sem.replit.app/api/v1/pixel/verify
```

## ⚠️ Revenue Bottleneck (Feb 21, 2026)

**$83.12 total Meta spend, 509 clicks, ZERO purchases (0.0% conversion rate)**

### Root Causes Identified (Priority Order)
1. 🔴 **Meta Pixel MISSING** — NO conversion tracking AT ALL → `POST /api/v1/pixel/install`
2. 🔴 **Klaviyo API key INVALID** — abandoned cart recovery emails NOT sending → `POST /api/v1/klaviyo/validate-key`
3. 🔴 **Campaign objective is LINK_CLICKS** — optimizes for clicks, not purchases (need OUTCOME_SALES once pixel is live)
4. 🟠 **Zero product reviews** — Judge.me installed but no reviews collected yet
5. 🟠 **No email capture popup** — losing all visitor emails who aren't ready to buy
6. 🟡 **"Made to Order" on all products** — may scare buyers expecting fast shipping
7. 🟡 **No urgency elements** — no scarcity, limited-time offers, or social proof

### Immediate Actions
1. ✅ Star performer campaign REACTIVATED at $25/day (was paused)
2. ✅ TikTok /campaigns endpoint added (BUG-12 fixed)
3. ✅ sync_data.py URL paths fixed (was using /api/ instead of /api/v1/)
4. ✅ Meta Pixel auto-installer endpoint created
5. ✅ Conversion funnel audit endpoint created
6. 🔴 **Republish Replit** for v2.5.2 → then run `POST /api/v1/pixel/install`
7. 🔴 Set valid Klaviyo API key via `POST /api/v1/klaviyo/validate-key`

## Architecture

**FastAPI** app (`main.py`) with 17 routers under `/api/v1/`:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `dashboard` | `/dashboard` | Aggregated metrics, sync, optimize, activity log, emergency controls, funnel, trends |
| `meta` | `/meta` | OAuth, campaigns, activate/pause/set-budget (CBO), ad creative CRUD, full-structure query |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video gen, targeting, performance |
| `tiktok_campaigns` | `/tiktok` | GET /campaigns with 7-day metrics (fixes BUG-12) |
| `campaigns` | `/campaigns` | CRUD, /active, DELETE /cleanup, POST /generate (AI ad copy via Claude API) |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart |
| `shopify` | `/shopify` | Admin API, webhooks, token refresh, customers, discounts |
| `google_ads` | `/google` | Google Ads campaigns (returns not_configured when no credentials) |
| `klaviyo` | `/klaviyo` | Flows, abandoned cart, email marketing, /set-key, /validate-key, /diagnose |
| `health` | `/health` | Deep health check, /reset-db, /scheduler |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | `/automation` | Status, start/stop, run-cycle, optimize, push-live, /recommendations, /force-sync |
| `store_health` | `/store-health` | Court Sportswear site checks: speed, pixels, CRO elements, SSL |
| `pixel_installer` | `/pixel` | **Meta Pixel auto-installer** — GET /status, POST /install, GET /verify |
| `conversion_audit` | `/dashboard` | **Conversion funnel audit** — GET /conversion-audit |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)

**Scheduler** (`scheduler.py`): APScheduler runs 7 jobs — daily optimization, 6h intra-day, 2h perf sync, daily snapshots, hourly spend check, hourly heartbeat, 20h Shopify token refresh.

## Active Meta Campaigns (Updated Feb 21, 2026)

| DB ID | Platform ID | Name | Budget | Status | Performance (7d) |
|-------|------------|------|--------|--------|-------------|
| 114 | 120206746647300364 | Ongoing website promotion | **$25/day** | **ACTIVE** ✅ | $57.62 spend, 472 clicks, 4.3% CTR, $0.12 CPC |
| 115 | 120241759616260364 | Court Sportswear - Sales | $5/day | **PAUSED** | $25.50 spend, 37 clicks, 2.8% CTR, $0.69 CPC |

## Store Health (Feb 21, 2026 — Live Check)

| Check | Status | Detail |
|-------|--------|--------|
| Homepage speed | ✅ | 888ms |
| Collection page | ✅ | 749ms, HTTP 200 |
| Judge.me reviews | ✅ | Installed (0 reviews) |
| **Meta Pixel** | ❌ | **NOT FOUND** |
| Free shipping bar | ✅ | Found |
| Klaviyo tracking | ✅ | Found (but API key invalid) |
| SSL certificate | ✅ | Valid until May 2026 |

## Key API Endpoints

```bash
# Health
curl https://auto-sem.replit.app/health

# META PIXEL (CRITICAL — run these first after Republish)
curl https://auto-sem.replit.app/api/v1/pixel/status
curl -X POST https://auto-sem.replit.app/api/v1/pixel/install
curl https://auto-sem.replit.app/api/v1/pixel/verify

# Conversion audit (full funnel diagnosis)
curl https://auto-sem.replit.app/api/v1/dashboard/conversion-audit

# Store health
curl https://auto-sem.replit.app/api/v1/store-health/check

# TikTok campaigns (new in v2.5.1)
curl https://auto-sem.replit.app/api/v1/tiktok/campaigns

# Meta campaigns
curl -X POST https://auto-sem.replit.app/api/v1/meta/activate-campaign \
  -H "Content-Type: application/json" -d '{"campaign_id": "120206746647300364"}'
curl -X POST https://auto-sem.replit.app/api/v1/meta/set-budget \
  -H "Content-Type: application/json" -d '{"campaign_id": "120206746647300364", "daily_budget_cents": 2500}'

# Klaviyo
curl -X POST https://auto-sem.replit.app/api/v1/klaviyo/validate-key \
  -H "Content-Type: application/json" -d '{"api_key": "pk_your_new_key"}'

# Deploy
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
```

## Optimizer Engine

### Awareness Mode (Current Setting)
`min_roas_threshold` = `0.0` — ROAS-based auto-pause and budget adjustments DISABLED.
All other rules active: CPC limits, landing page flags, scale-winner, emergency pause.
**After first sale:** Set back to 1.5 via `PUT /api/v1/settings/`.

## Critical Rules

1. **Meta budgets are in cents** — $25/day = 2500 in the API
2. **CBO campaigns** — budget set at campaign level, not adset level
3. **Deploy gap:** deploy/pull API updates workspace but NOT production. Must Republish in Replit UI.
4. **After Republish:** Run `POST /api/v1/pixel/install` immediately to fix conversion tracking
5. **After first sale:** Set min_roas_threshold back to 1.5
6. **Shopify API for products:** Use Shopify-first approach (not Printful API)

## Known Bugs

| Bug | Status | Fix |
|-----|--------|-----|
| BUG-11: Klaviyo hardcoded fallback key rotted | Fixed v2.5.0 | Removed hardcoded key |
| BUG-12: TikTok /campaigns 404 | Fixed v2.5.1 | Added tiktok_campaigns.py |
| BUG-13: Klaviyo API key invalid in production | **OPEN** | Need new key via /validate-key |
| BUG-14: Deploy/pull doesn't update production | **KNOWN** | Must Republish in Replit UI |
| BUG-15: Meta Pixel missing from store | **OPEN** | Run POST /api/v1/pixel/install after Republish |
| BUG-16: Campaign objective LINK_CLICKS not OUTCOME_SALES | **OPEN** | Create new conversion campaign after pixel installed |

## Phase History

- **Phases 1-12:** Core infrastructure through ad-level optimization (see git log)
- **Phase 13 (Feb 21):** Klaviyo fix, store health monitor, conversion funnel tracking, pre-revenue optimizer (v2.5.0)
- **Phase 14 (Feb 21 PM):** CTO audit sprint:
  - Star performer campaign reactivated at $25/day
  - TikTok /campaigns endpoint (tiktok_campaigns.py)
  - sync_data.py paths fixed (/api/ → /api/v1/)
  - **CRITICAL DISCOVERY: Meta Pixel missing from court-sportswear.com**
  - Meta Pixel auto-installer built (pixel_installer.py)
  - Conversion funnel audit endpoint (conversion_audit.py)
  - 12 Claude Code tasks created (autosem-claude-tasks.md)
  - Version bumped to 2.5.2
