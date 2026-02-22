# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)
**Claude Code Tasks:** See `autosem-claude-tasks.md` for 12 revenue-prioritized tasks

## Current Version: 2.6.0 (GitHub) — v2.5.0 deployed (needs Republish)

**Deployment:** Reserved-VM mode — `POST /api/v1/deploy/pull` updates production directly. Auto-deploy via GitHub Actions on push to main (`.github/workflows/deploy.yml`).

**⚡ NEW in v2.6.0:** Meta Pixel auto-installs on app startup. 30 seconds after boot, a background thread checks court-sportswear.com for `fbq()`. If missing, it calls `POST /api/v1/pixel/install` internally. No manual action needed — just Republish.

17 routers, 120+ endpoints. Production smoke-tested: 51/54 pass. AI ad copy generation via Claude API (POST /campaigns/generate). Scheduler: midnight CST daily optimization (cron), hourly spend checks, daily performance snapshots, heartbeat ticks. Optimizer awareness-mode fix (won't auto-pause pre-revenue campaigns). Ad-level CRUD fully deployed. Klaviyo hardcoded key removed (BUG-11 fixed). Store health monitor. Meta Pixel auto-installer. Conversion funnel audit. TikTok /campaigns endpoint.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy via API (reserved-VM — updates production directly):
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
# Auto-deploy: pushes to main trigger .github/workflows/deploy.yml

# Swagger docs
https://auto-sem.replit.app/docs
```

```bash
# Run tests
pytest tests/ -v --tb=short --cov=app

# Production smoke test
python scripts/smoke_test.py
```

## 🚨 CRITICAL: Meta Pixel Auto-Install (Feb 22, 2026)

**The Meta Pixel (fbq) is completely missing from court-sportswear.com.**
This is the #1 reason for 0 conversions on 509 ad clicks ($83 spend).

### v2.6.0 Fix: Automatic on startup
When the app boots, a background thread (30s delay) checks for the pixel. If missing, it auto-installs via `POST /api/v1/pixel/install`. **Just Republish to v2.6.0 and it fixes itself.**

### Manual fix (if auto-install fails):
```bash
curl https://auto-sem.replit.app/api/v1/pixel/status
curl -X POST https://auto-sem.replit.app/api/v1/pixel/install
curl https://auto-sem.replit.app/api/v1/pixel/verify
```

## ⚠️ Revenue Bottleneck (Feb 21, 2026)

**$83.12 total Meta spend, 509 clicks, ZERO purchases (0.0% conversion rate)**

### Root Causes Identified (Priority Order)
1. 🔴 **Meta Pixel MISSING** — NO conversion tracking AT ALL → Fixed in v2.6.0 (auto-installs on startup)
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
6. ✅ Startup auto-installer added (v2.6.0) — pixel installs automatically on boot
7. ✅ Reserved-VM deployment — no more manual Republish after the switch
8. 🔴 **ONE final Republish needed** to switch to reserved-VM and get v2.6.0 live
9. 🔴 Set valid Klaviyo API key via `POST /api/v1/klaviyo/validate-key`

## Architecture

**FastAPI** app (`main.py`) with 17 routers under `/api/v1/`:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `dashboard` | `/dashboard` | Aggregated metrics, sync, optimize, activity log, emergency controls, funnel, trends |
| `meta` | `/meta` | OAuth, campaigns, activate/pause/set-budget (CBO), ad creative CRUD, A/B testing |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video gen, targeting, performance |
| `tiktok_campaigns` | `/tiktok` | GET /campaigns with 7-day metrics (fixes BUG-12) |
| `campaigns` | `/campaigns` | CRUD, /active, DELETE /cleanup, POST /generate (AI ad copy via Claude API) |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart (reserved-VM) |
| `shopify` | `/shopify` | Admin API, webhooks, token refresh, customers, discounts |
| `google_ads` | `/google` | Google Ads campaigns, Shopping feed, performance |
| `klaviyo` | `/klaviyo` | Flows, abandoned cart, email marketing, /set-key, /validate-key, /diagnose |
| `health` | `/health` | Deep health check, /reset-db, /scheduler |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | `/automation` | Status, start/stop, run-cycle, optimize, push-live, /recommendations, /force-sync |
| `store_health` | `/store-health` | Court Sportswear site checks: speed, pixels, CRO elements, SSL |
| `pixel_installer` | `/pixel` | **Meta Pixel auto-installer** — GET /status, POST /install, GET /verify |
| `conversion_audit` | `/dashboard` | **Conversion funnel audit** — GET /conversion-audit |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)

**Services:** (`app/services/`)
- `meta_capi.py` — Server-side Conversions API for Purchase, AddToCart, InitiateCheckout
- `checkout_audit.py` — Shopify abandoned checkout analysis
- `daily_report.py` — Automated daily performance email (08:00 UTC)
- `attribution.py` — Revenue attribution pipeline (UTM → campaign → order)
- `google_ads/` — Google Ads service layer

**Scheduler** (`scheduler.py`): APScheduler runs 8 jobs — daily optimization, 6h intra-day, 2h perf sync, daily snapshots, hourly spend check, hourly heartbeat, 08:00 UTC daily report email, 20h Shopify token refresh.

**Startup sequence** (`main.py`):
1. Init database
2. Register 17 routers
3. Start APScheduler
4. Register Shopify webhooks
5. **Auto-install Meta Pixel** (30s delay, background thread)

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
| **Meta Pixel** | ❌ → ✅ after Republish | **Auto-installs on v2.6.0 startup** |
| Free shipping bar | ✅ | Found |
| Klaviyo tracking | ✅ | Found (but API key invalid) |
| SSL certificate | ✅ | Valid until May 2026 |

## Key API Endpoints

```bash
# Health
curl https://auto-sem.replit.app/health

# META PIXEL (auto-installs on v2.6.0 startup — manual fallback below)
curl https://auto-sem.replit.app/api/v1/pixel/status
curl -X POST https://auto-sem.replit.app/api/v1/pixel/install
curl https://auto-sem.replit.app/api/v1/pixel/verify

# Conversion audit (full funnel diagnosis)
curl https://auto-sem.replit.app/api/v1/dashboard/conversion-audit

# Deploy (reserved-VM — updates production directly)
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
curl https://auto-sem.replit.app/api/v1/deploy/status

# Store health
curl https://auto-sem.replit.app/api/v1/store-health/check

# TikTok campaigns
curl https://auto-sem.replit.app/api/v1/tiktok/campaigns

# Meta campaigns
curl -X POST https://auto-sem.replit.app/api/v1/meta/activate-campaign \
  -H "Content-Type: application/json" -d '{"campaign_id": "120206746647300364"}'

# A/B Testing
curl -X POST https://auto-sem.replit.app/api/v1/meta/create-test \
  -H "Content-Type: application/json" -d '{"original_ad_id": "...", "variant_type": "headline", "variant_value": "New Headline"}'
curl https://auto-sem.replit.app/api/v1/meta/test-results

# Klaviyo
curl -X POST https://auto-sem.replit.app/api/v1/klaviyo/validate-key \
  -H "Content-Type: application/json" -d '{"api_key": "pk_your_new_key"}'
```

## Optimizer Engine

### Awareness Mode (Current Setting)
`min_roas_threshold` = `0.0` — ROAS-based auto-pause and budget adjustments DISABLED.
All other rules active: CPC limits, landing page flags, scale-winner, emergency pause.
**After first sale:** Set back to 1.5 via `PUT /api/v1/settings/`.

## Critical Rules

1. **Meta budgets are in cents** — $25/day = 2500 in the API
2. **CBO campaigns** — budget set at campaign level, not adset level
3. **Deploy:** Reserved-VM mode — deploy/pull updates production directly. Auto-deploy on push to main via GitHub Actions.
4. **Pixel auto-install:** v2.6.0+ automatically installs Meta Pixel 30s after startup
5. **After first sale:** Set min_roas_threshold back to 1.5
6. **Shopify API for products:** Use Shopify-first approach (not Printful API)

## Known Bugs

| Bug | Status | Fix |
|-----|--------|-----|
| BUG-11: Klaviyo hardcoded fallback key rotted | Fixed v2.5.0 | Removed hardcoded key |
| BUG-12: TikTok /campaigns 404 | Fixed v2.5.1 | Added tiktok_campaigns.py |
| BUG-13: Klaviyo API key invalid in production | **OPEN** | Need new key via /validate-key |
| BUG-14: Deploy/pull doesn't update production | **Fixed v2.5.9** | Switched to reserved-VM + GitHub Actions auto-deploy |
| BUG-15: Meta Pixel missing from store | **Fixed v2.6.0** | Auto-installs on startup; manual: POST /pixel/install |
| BUG-16: Campaign objective LINK_CLICKS not OUTCOME_SALES | **Fixed v2.5.5** | POST /meta/create-conversion-campaign, POST /meta/switch-objective |

## Phase History

- **Phases 1-12:** Core infrastructure through ad-level optimization (see git log)
- **Phase 13 (Feb 21):** Klaviyo fix, store health monitor, conversion funnel tracking, pre-revenue optimizer (v2.5.0)
- **Phase 14 (Feb 21 PM):** CTO audit sprint — pixel installer, conversion audit, TikTok fix (v2.5.2)
- **Phase 15 (Feb 21):** Deploy restart fix, status/verify endpoints (v2.5.3)
- **Phase 16 (Feb 21):** Automated daily performance report with email delivery (v2.5.4)
- **Phase 17 (Feb 21):** Conversion campaign creation, objective switching (v2.5.5)
- **Phase 18 (Feb 21):** Review solicitation — Judge.me + Klaviyo (v2.5.6)
- **Phase 19 (Feb 21):** A/B testing with statistical significance and auto-optimization (v2.5.7)
- **Phase 20 (Feb 21):** pytest framework, 63 tests, GitHub Actions CI (v2.5.8)
- **Phase 21 (Feb 21):** GitHub Actions auto-deploy, reserved-VM deployment (v2.5.9)
- **Phase 22 (Feb 22):** Meta Pixel auto-install on startup — pixel installs automatically 30s after boot. ONE Republish needed to activate. (v2.6.0)
