# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)

## Current Version: 2.4.0

13 routers, 90+ endpoints. Production smoke-tested: 51/54 pass. AI ad copy generation via Claude API (POST /campaigns/generate). Scheduler: midnight CST daily optimization (cron), hourly spend checks, heartbeat ticks. Optimizer awareness-mode fix (won't auto-pause pre-revenue campaigns). Ad-level CRUD fully deployed.

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
| `meta` | `/meta` | OAuth, campaigns, activate/pause/set-budget (CBO), ad creative CRUD, full-structure query, ad-level update/pause |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video generation, targeting |
| `campaigns` | `/campaigns` | CRUD, /active, DELETE /cleanup, POST /generate (AI ad copy via Claude API) |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart |
| `shopify` | `/shopify` | Admin API, webhooks, token refresh, customers, discounts |
| `google_ads` | `/google` | Google Ads campaigns (returns not_configured when no credentials) |
| `klaviyo` | `/klaviyo` | Klaviyo flows, abandoned cart, email marketing, POST /set-key, auto-init from env |
| `health` | `/health` | Deep health check, GET /reset-db for error recovery |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | `/automation` | Status, start/stop, run-cycle, create-campaigns, optimize, push-live, activity-log |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)
Tables: products, campaigns, meta_tokens, tiktok_tokens, activity_logs, settings

**Scheduler** (`scheduler.py`): APScheduler runs 6 jobs:
- Daily optimization at midnight CST (06:00 UTC cron trigger)
- Optimization every 6 hours (interval, intra-day)
- Performance sync every 2 hours
- Hourly spend check (compares active budgets vs daily_spend_limit, alerts at 90%)
- Scheduler heartbeat tick every hour (proof-of-life logging)
- Shopify token refresh every 20 hours

## Active Meta Campaigns (Updated Feb 20, 2026)

| DB ID | Platform ID | Name | Budget | Status | Performance |
|-------|------------|------|--------|--------|-------------|
| 114 | 120206746647300364 | Ongoing website promotion | **$20/day** | **ACTIVE** | $0.11 CPC, 4.83% CTR ⭐ |
| 115 | 120241759616260364 | Court Sportswear - Sales | $5/day | **PAUSED** | $0.73 CPC — stopped |

### Ad-Level Status (Ongoing Campaign)
| Ad ID | Creative | Destination URL | Status |
|-------|----------|-----------------|--------|
| 120206746647430364 | Tennis TShirts image 1 | `/collections/all-mens-t-shirts` | ✅ ACTIVE |
| 120206746647460364 | Tennis TShirts image 2 | `/collections/all-mens-t-shirts` | ✅ ACTIVE |
| 120206746647450364 | Dynamic catalog ad | Dynamic | ✅ ACTIVE |
| 120206746647410364 | Tennis TShirts (old) | `http://www.court-sportswear.com/` | ⏸️ PAUSED |
| 120206746647440364 | Tennis TShirts (old) | `http://www.court-sportswear.com/` | ⏸️ PAUSED |

**Key change Feb 20:** Paused 2 ads still pointing to homepage. All active ads now deep-link to collection page. This was only possible via ad-level API endpoints (GET /meta/campaigns/{id}/full-structure, PUT /meta/ads/{id}/update).

### TikTok — ALL DISABLED
All 19 TikTok campaigns DISABLED. Total spend: $11.11. Audience targeting catastrophically broken (81% gamers, 0% tennis players, 71% non-US traffic despite US-only setting). Do not reactivate.

## Optimizer Engine

### Awareness Mode (Current Setting)
`min_roas_threshold` is set to `0.0` via settings API. This means:
- **ROAS-based auto-pause is DISABLED** — campaigns won't be paused for zero revenue
- **ROAS-based budget adjustments are DISABLED** — no budget cuts for low ROAS
- **All other rules still active:** CPC limits, landing page flags, scale-winner, emergency pause
- **To re-enable:** `PUT /api/v1/settings/ {"min_roas_threshold": 1.5}`

### Auto-Action Rules
| Rule | Condition | Action | Respects awareness mode? |
|------|-----------|--------|--------------------------|
| pause_underperformer | ROAS < threshold/3 after $20+ spend | Pause campaign | ✅ Yes — skipped when threshold=0 |
| flag_landing_page_pause | CTR>3%, conv<1%, CPC>$1.00 | Pause campaign | No — always active |
| flag_landing_page_budget_cut | CTR>3%, conv<1%, CPC>$0.50 | Cut budget 25% | No — always active |
| scale_winner | CTR>3%, CPC<$0.20, 10+ clicks | Increase budget 20% (cap $25) | No — always active |
| budget_increase | ROAS > 1.5x threshold | Increase budget 25% | ✅ Yes — skipped when threshold=0 |
| budget_decrease | ROAS < threshold, $50+ spend | Decrease budget 25% | ✅ Yes — skipped when threshold=0 |
| emergency_pause | Net loss > $500 | Pause ALL campaigns | No — always active |

### ⚠️ BUG-10 FIX (Feb 20): Optimizer used hardcoded ROAS < 0.5 check
The optimizer had a hardcoded `roas < 0.5` pause rule that ignored the `min_roas_threshold` setting. This caused it to auto-pause the Ongoing campaign (which had 0 ROAS because no sales yet, despite excellent $0.11 CPC). Fixed to respect settings — when threshold is 0, ROAS-based pauses are completely skipped.

## Court Sportswear CRO Status (Feb 20, 2026)

### ✅ Completed
- Free shipping announcement bar (links to /collections/all-mens-t-shirts)
- Judge.me reviews installed on all product pages
- Meta ad destination URLs changed to collection page (deep-link)
- 2 old homepage-pointing ads paused
- 23/23 product tags optimized with CRO keywords
- Shopify orders/create webhook registered
- Meta Pixel, TikTok Pixel, GA4, GTM all active
- Cookie consent with Google Consent Mode v2

### ✅ Klaviyo
- Abandoned cart flow: **LIVE** (flow VFSVJd, 1 email live, 1 draft)
- 2 profiles collected (dennisdeuce@gmail.com, julierpenn3@gmail.com)
- 44 Shopify customers total, 29 with orders, $2,229.50 lifetime revenue

### ❌ Still Missing
- **Email capture popup on store** — no Klaviyo form/popup installed on court-sportswear.com
- **Abandoned cart email #2** — still in draft status in Klaviyo
- **Google Ads** — router exists but no credentials configured

## Key API Endpoints for Common Tasks

```bash
# Check everything is running
curl https://auto-sem.replit.app/health

# Sync latest Meta performance data
curl -X POST https://auto-sem.replit.app/api/v1/automation/sync-performance

# Run optimization (respects awareness mode)
curl -X POST https://auto-sem.replit.app/api/v1/automation/optimize

# Get full campaign structure (campaign → adsets → ads)
curl https://auto-sem.replit.app/api/v1/meta/campaigns/120206746647300364/full-structure

# Pause/activate a specific ad
curl -X PUT https://auto-sem.replit.app/api/v1/meta/ads/{ad_id}/update \
  -H "Content-Type: application/json" -d '{"status": "PAUSED"}'

# Check automation settings
curl https://auto-sem.replit.app/api/v1/settings/

# Update settings (e.g., re-enable ROAS optimization after first sale)
curl -X PUT https://auto-sem.replit.app/api/v1/settings/ \
  -H "Content-Type: application/json" -d '{"min_roas_threshold": 1.5}'

# Get Shopify products
curl https://auto-sem.replit.app/api/v1/shopify/products

# Update product tags
curl -X PUT https://auto-sem.replit.app/api/v1/shopify/products/{product_id} \
  -H "Content-Type: application/json" -d '{"tags": "new,tags,here"}'

# Check Klaviyo status
curl https://auto-sem.replit.app/api/v1/klaviyo/flows/VFSVJd
```

## Deploy Flow

### Workspace Git Checkout (Replit)
```bash
# In Replit Shell:
git fetch origin main
git reset --hard origin/main
cat app/version.py  # verify version
# Then click "Republish" in Replit Deployments UI
```

### Via API:
```bash
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
```

**Important:** After Republish, the .git directory may be wiped. Re-run `git fetch + reset` if needed before next deploy.

## Environment Variables (Replit Secrets)

`DATABASE_URL`, `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`,
`META_PAGE_ID`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE`, `DEPLOY_KEY`, `KLAVIYO_API_KEY`,
`GITHUB_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`

## Critical Rules

1. **Never modify AutoSEM code without verifying it won't break court-sportswear.com** — both systems are interconnected via webhooks, pixels, and API calls
2. **Meta API calls must go through AutoSEM** — `graph.facebook.com` is blocked in Claude's bash environment
3. **Meta budgets are in cents** — $20/day = 2000 in the API
4. **CBO campaigns** — budget set at campaign level, not adset level
5. **After first sale:** Set min_roas_threshold back to 1.5 via settings API
6. **Shopify API for products:** Use Shopify-first approach (not Printful API) due to integration limitations

## Known Bugs

| Bug | Status | Fix |
|-----|--------|-----|
| BUG-1: Scheduler optimizer missing DB session | ✅ Fixed v1.8.0 | |
| BUG-2: Klaviyo env var not loading | ✅ Fixed v2.0.0 | Auto-init from env |
| BUG-3: Shopify scopes insufficient | ✅ Fixed v1.9.0 | App reinstalled |
| BUG-4: Deploy auto-restart | ✅ Fixed v1.8.0 | os._exit(0) |
| BUG-5: Optimizer data pipeline | ✅ Fixed v2.0.0 | PerformanceSyncService |
| BUG-6: Optimizer CBO budget | ✅ Fixed v1.10.0 | Campaign-first, adset fallback |
| BUG-7: Automation router missing Query import | ✅ Fixed v2.3.0 | Added import |
| BUG-8: Shopify 500 on invalid product ID | ✅ Fixed v2.3.0 | Try/except |
| BUG-9: Shopify 500 on invalid collection ID | ✅ Fixed v2.3.0 | Try/except |
| BUG-10: Optimizer ignores min_roas_threshold=0 | ✅ Fixed v2.4.0 | Awareness mode |

## Phase History

- **Phase 1-3:** Core infrastructure, bug fixes, dashboard, scheduler
- **Phase 4:** Optimizer auto-actions with CPC thresholds, budget scaling
- **Phase 5-6:** Deploy system, campaign schema
- **Phase 7:** Shopify TOML, Klaviyo, JSON-LD, sitemap
- **Phase 8:** Deploy restart, DB error recovery, dashboard polish
- **Phase 9:** Order webhooks, discounts, revenue dashboard, workspace git checkout
- **Phase 10A:** Optimizer settings fix, performance sync pipeline, Klaviyo auto-init
- **Phase 10B:** Meta ad creative CRUD (adset/ad query, full-structure, create/update/delete)
- **Phase 10C:** NotificationService, Klaviyo fallback key
- **Phase 11:** Production smoke test (51/54), scheduler upgrade (6 jobs), AI ad copy generation
- **Phase 12 (Feb 20):** Ad-level optimization — paused homepage-pointing ads, deep-linked active ads to collection page. Optimizer awareness-mode fix. Sales campaign paused ($0.73 CPC waste stopped). 23/23 product tags optimized. (v2.4.0)
