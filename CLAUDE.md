# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous advertising platform built with FastAPI. It manages multi-platform ad campaigns (Meta, TikTok, Google Ads) with profitability-first algorithms for Court Sportswear, a tennis/pickleball apparel e-commerce store on Shopify.

**Live:** https://auto-sem.replit.app
**Dashboard:** https://auto-sem.replit.app/dashboard
**Store:** https://court-sportswear.com
**Repo:** https://github.com/Dennisdeuce/AutoSEM (branch: main)
**Claude Code Tasks:** See `autosem-claude-tasks.md` for 12 revenue-prioritized tasks

## Current Version: 2.5.0 (GitHub) / 2.4.0 (Live)

⚠️ **DEPLOY GAP**: GitHub has v2.5.0 but live deployment is v2.4.0 (13 routers, missing store_health).
To deploy: Replit Shell → `git fetch origin main && git reset --hard origin/main` → Republish in Deployments UI.

14 routers, 100+ endpoints. Production smoke-tested: 51/54 pass. AI ad copy generation via Claude API (POST /campaigns/generate). Scheduler: midnight CST daily optimization (cron), hourly spend checks, daily performance snapshots, heartbeat ticks. Optimizer awareness-mode fix (won't auto-pause pre-revenue campaigns). Ad-level CRUD fully deployed. Klaviyo hardcoded key removed (BUG-11 fixed). Store health monitor. Conversion funnel tracking. Pre-revenue optimizer recommendations.

## Commands

```bash
# Run locally
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Deploy (from Replit Shell — workspace is now a git checkout):
git fetch origin main && git reset --hard origin/main
# Then click "Republish" in Replit Deployments UI

# Alternative deploy via API (updates workspace, not production):
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"

# Swagger docs
https://auto-sem.replit.app/docs
```

No test framework configured. Use Swagger UI or curl for testing.

## ⚠️ CRITICAL: Revenue Bottleneck (Feb 21, 2026)

**$83.12 total Meta spend, 509 clicks, ZERO purchases (0.0% conversion rate)**

### Root Causes Identified
1. **Klaviyo API key INVALID** — abandoned cart recovery emails NOT sending
2. **Zero product reviews** — Judge.me installed but no reviews collected yet
3. **No email capture popup** — losing all visitor emails who aren't ready to buy
4. **"Made to Order" on all products** — may scare buyers expecting fast shipping
5. **Page weight ~975KB, 81 scripts** — slow load especially on mobile (89% of traffic)
6. **No urgency elements** — no scarcity, limited-time offers, or social proof
7. **Premium pricing ($26-37)** without sufficient value justification visible

### Immediate Actions Needed
1. ✅ Star performer campaign REACTIVATED at $25/day (was paused)
2. 🔴 Republish Replit deployment to get v2.5.0 live
3. 🔴 Set valid Klaviyo API key via POST /api/v1/klaviyo/validate-key
4. 🔴 Add email capture popup on court-sportswear.com
5. 🔴 Add at least 3-5 product reviews (Judge.me review request emails)
6. 🟡 Audit landing page load speed and mobile experience
7. 🟡 Add trust signals above fold: shipping time, return policy, satisfaction guarantee

## Architecture

**FastAPI** app (`main.py`) with 14 routers under `/api/v1/`:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `dashboard` | `/dashboard` | Aggregated metrics, sync-meta, optimize-now, activity log, emergency controls, funnel, trends |
| `meta` | `/meta` | OAuth, campaigns, activate/pause/set-budget (CBO), ad creative CRUD, full-structure query, ad-level update/pause |
| `tiktok` | `/tiktok` | TikTok OAuth, campaign launch, video generation, targeting, GET /campaigns |
| `campaigns` | `/campaigns` | CRUD, /active, DELETE /cleanup, POST /generate (AI ad copy via Claude API) |
| `products` | `/products` | Shopify product sync and management |
| `settings` | `/settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | `/deploy` | GitHub webhook + deploy/pull with auto-restart |
| `shopify` | `/shopify` | Admin API, webhooks, token refresh, customers, discounts |
| `google_ads` | `/google` | Google Ads campaigns (returns not_configured when no credentials) |
| `klaviyo` | `/klaviyo` | Klaviyo flows, abandoned cart, email marketing, POST /set-key, /validate-key, /diagnose, auto-init from env |
| `health` | `/health` | Deep health check, GET /reset-db for error recovery, GET /scheduler for job status |
| `seo` | `/seo` | JSON-LD structured data, XML sitemap generation |
| `automation` | `/automation` | Status, start/stop, run-cycle, create-campaigns, optimize, push-live, activity-log, /recommendations, /force-sync |
| `store_health` | `/store-health` | Court Sportswear site checks: speed, pixels, CRO elements, SSL (v2.5.0 only) |

**Database:** PostgreSQL on Neon (`ep-delicate-queen-ah2ayed9.c-3.us-east-1.aws.neon.tech/neondb`)
Tables: products, campaigns, campaign_history, meta_tokens, tiktok_tokens, activity_logs, settings, performance_snapshots

**Scheduler** (`scheduler.py`): APScheduler runs 7 jobs:
- Daily optimization at midnight CST (06:00 UTC cron trigger)
- Optimization every 6 hours (interval, intra-day)
- Performance sync every 2 hours
- Daily performance snapshot at 06:15 UTC (after optimization)
- Hourly spend check (compares active budgets vs daily_spend_limit, alerts at 90%)
- Scheduler heartbeat tick every hour (proof-of-life logging)
- Shopify token refresh every 20 hours

## Active Meta Campaigns (Updated Feb 21, 2026)

| DB ID | Platform ID | Name | Budget | Status | Performance (7d) |
|-------|------------|------|--------|--------|-------------|
| 114 | 120206746647300364 | Ongoing website promotion | **$25/day** | **ACTIVE** ✅ | $57.62 spend, 472 clicks, 4.3% CTR, $0.12 CPC |
| 115 | 120241759616260364 | Court Sportswear - Sales | $5/day | **PAUSED** | $25.50 spend, 37 clicks, 2.8% CTR, $0.69 CPC |

**Feb 21 changes:** Star performer was PAUSED, reactivated via API and budget restored to $25/day ($10→$25).

### Ad-Level Status (Ongoing Campaign)
| Ad ID | Creative | Destination URL | Status |
|-------|----------|-----------------|--------|
| 120206746647430364 | Tennis TShirts image 1 | `/collections/all-mens-t-shirts` | ACTIVE |
| 120206746647460364 | Tennis TShirts image 2 | `/collections/all-mens-t-shirts` | ACTIVE |
| 120206746647450364 | Dynamic catalog ad | Dynamic | ACTIVE |
| 120206746647410364 | Tennis TShirts (old) | `http://www.court-sportswear.com/` | PAUSED |
| 120206746647440364 | Tennis TShirts (old) | `http://www.court-sportswear.com/` | PAUSED |

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
| pause_underperformer | ROAS < threshold/3 after $20+ spend | Pause campaign | Yes — skipped when threshold=0 |
| flag_landing_page_pause | CTR>3%, conv<1%, CPC>$1.00 | Pause campaign | No — always active |
| flag_landing_page_budget_cut | CTR>3%, conv<1%, CPC>$0.50 | Cut budget 25% | No — always active |
| scale_winner | CTR>3%, CPC<$0.20, 10+ clicks | Increase budget 20% (cap $25) | No — always active |
| budget_increase | ROAS > 1.5x threshold | Increase budget 25% | Yes — skipped when threshold=0 |
| budget_decrease | ROAS < threshold, $50+ spend | Decrease budget 25% | Yes — skipped when threshold=0 |
| emergency_pause | Net loss > $500 | Pause ALL campaigns | No — always active |

## Court Sportswear Product Catalog (23 Products)

All active, all "Made to Order". Price range: $24.95 - $36.75.
- Performance Tees: 18 styles ($24.95-$26.95) — tennis beer cans, pickleball cans, retro gaming, vintage illustrations
- Hoodies: 2 styles ($36.75)
- Tank Tops: 1 style ($27.95)
- Women's: 1 style ($26.00)
- Key tags: Tennis, Pickleball, Beer & Tennis, Retro, Performance, Dri-Fit, UPF Protection

## Court Sportswear CRO Status (Feb 21, 2026)

### Completed
- Free shipping announcement bar (links to /collections/all-mens-t-shirts)
- Judge.me reviews installed on all product pages (0 reviews collected)
- Meta ad destination URLs changed to collection page (deep-link)
- 2 old homepage-pointing ads paused
- 23/23 product tags optimized with CRO keywords
- Shopify orders/create webhook registered
- Meta Pixel, TikTok Pixel, GA4, GTM all active
- Cookie consent with Google Consent Mode v2
- Star performer Meta campaign reactivated at $25/day

### Klaviyo
- Abandoned cart flow: **LIVE** (flow VFSVJd, 1 email live, 1 draft)
- ⚠️ **API KEY INVALID** — emails NOT sending
- 2 profiles collected
- 44 Shopify customers total, 29 with orders, $2,229.50 lifetime revenue

### Still Missing (Revenue Blockers)
- 🔴 **Valid Klaviyo API key** — abandoned cart emails broken
- 🔴 **Email capture popup** — no Klaviyo form/popup on court-sportswear.com
- 🔴 **Product reviews** — 0 reviews on any product (Judge.me installed but unused)
- 🟡 **Landing page speed** — 975KB, 81 scripts, slow for 89% mobile traffic
- 🟡 **Trust signals** — no visible shipping time, return policy, or satisfaction guarantee above fold
- 🟡 **Abandoned cart email #2** — still in draft in Klaviyo
- 🟡 **Google Ads** — router exists but no credentials configured
- 🟡 **Revenue attribution** — can't track Meta click → Shopify purchase path

## Key API Endpoints for Common Tasks

```bash
# Check everything is running
curl https://auto-sem.replit.app/health

# Sync latest Meta performance data
curl -X POST https://auto-sem.replit.app/api/v1/automation/sync-performance

# Force sync with verbose output (v2.5.0 only)
curl -X POST https://auto-sem.replit.app/api/v1/automation/force-sync

# Run optimization (respects awareness mode)
curl -X POST https://auto-sem.replit.app/api/v1/automation/optimize

# Get optimizer recommendations (v2.5.0 only)
curl https://auto-sem.replit.app/api/v1/automation/recommendations

# Activate/pause Meta campaign
curl -X POST https://auto-sem.replit.app/api/v1/meta/activate-campaign \
  -H "Content-Type: application/json" -d '{"campaign_id": "120206746647300364"}'

# Set Meta campaign budget (in cents: 2500 = $25.00)
curl -X POST https://auto-sem.replit.app/api/v1/meta/set-budget \
  -H "Content-Type: application/json" -d '{"campaign_id": "120206746647300364", "daily_budget_cents": 2500}'

# Validate a new Klaviyo key
curl -X POST https://auto-sem.replit.app/api/v1/klaviyo/validate-key \
  -H "Content-Type: application/json" -d '{"api_key": "pk_your_new_key"}'

# Diagnose Klaviyo key issues (v2.5.0 only)
curl https://auto-sem.replit.app/api/v1/klaviyo/diagnose

# Store health check (v2.5.0 only)
curl https://auto-sem.replit.app/api/v1/store-health/check

# Conversion funnel (v2.5.0 only)
curl https://auto-sem.replit.app/api/v1/dashboard/funnel
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

### Via API (updates workspace code only, NOT production deployment):
```bash
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
# NOTE: This updates workspace files and restarts the dev process.
# The production deployment at auto-sem.replit.app requires Republish in Replit UI.
```

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
7. **Deploy gap:** deploy/pull API updates workspace but NOT production. Must Republish in Replit UI.

## Known Bugs

| Bug | Status | Fix |
|-----|--------|-----|
| BUG-1: Scheduler optimizer missing DB session | Fixed v1.8.0 | |
| BUG-2: Klaviyo env var not loading | Fixed v2.0.0 | Auto-init from env |
| BUG-3: Shopify scopes insufficient | Fixed v1.9.0 | App reinstalled |
| BUG-4: Deploy auto-restart | Fixed v1.8.0 | os._exit(0) |
| BUG-5: Optimizer data pipeline | Fixed v2.0.0 | PerformanceSyncService |
| BUG-6: Optimizer CBO budget | Fixed v1.10.0 | Campaign-first, adset fallback |
| BUG-7: Automation router missing Query import | Fixed v2.3.0 | Added import |
| BUG-8: Shopify 500 on invalid product ID | Fixed v2.3.0 | Try/except |
| BUG-9: Shopify 500 on invalid collection ID | Fixed v2.3.0 | Try/except |
| BUG-10: Optimizer ignores min_roas_threshold=0 | Fixed v2.4.0 | Awareness mode |
| BUG-11: Klaviyo hardcoded fallback key rotted | Fixed v2.5.0 | Removed hardcoded key, env/DB only + /validate-key |
| BUG-12: TikTok /campaigns 404 | Fixed v2.5.1 | Added GET /campaigns endpoint |
| BUG-13: Klaviyo API key invalid in production | **OPEN** | Need new key via /validate-key after Republish |
| BUG-14: Deploy/pull doesn't update production | **KNOWN** | Must Republish in Replit UI after deploy/pull |

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
- **Phase 13 (Feb 21):** Revenue pipeline fix — Klaviyo hardcoded key removed (BUG-11), validate-key/diagnose endpoints, retry logic with exponential backoff, scheduler resilience (3 retries per job, job tracking, /health/scheduler), store health monitor (7-point check on court-sportswear.com), conversion funnel tracking (/dashboard/funnel with drop-off warnings), pre-revenue optimizer recommendations, daily performance snapshots (PerformanceSnapshotModel + /dashboard/trends), force-sync endpoint. 14 routers, 100+ endpoints. (v2.5.0)
- **Phase 14 (Feb 21 PM):** CTO audit — Star performer campaign reactivated at $25/day (was paused at $10/day). Workspace code updated to v2.5.0 via deploy/pull API. TikTok /campaigns endpoint added. autosem-claude-tasks.md created with 12 revenue-prioritized tasks. Conversion bottleneck diagnosed (509 clicks, $83 spend, 0 purchases). Root causes: invalid Klaviyo key, 0 reviews, no email capture, slow pages. Production still needs Republish for v2.5.0.
