# AutoSEM Claude Code Tasks

These tasks are designed to be pasted into Claude Code (Git Bash) one at a time, in order of revenue impact. Each task is self-contained. Always start by reading CLAUDE.md to understand the project structure.

**Repo**: Dennisdeuce/AutoSEM (branch: main)
**Live**: https://auto-sem.replit.app
**Stack**: Python 3.11, FastAPI, PostgreSQL (Neon), APScheduler

---

## TASK 0: Deploy v2.5.0 to Replit

Paste into Claude Code:
```
Read CLAUDE.md first. The live deployment at https://auto-sem.replit.app is running v2.4.0 but the GitHub repo is at v2.5.0. v2.5.0 includes the store_health router and Klaviyo fixes that are missing from production.

1. Trigger the deploy API: curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull -H "X-Deploy-Key: autosem-deploy-2026"
2. Wait 10 seconds for the process to restart
3. Verify deployment by checking /health returns v2.5.0 and router_count is 14
4. If still v2.4.0, the Replit production deployment needs Republish:
   - Open Replit Shell: git fetch origin main && git reset --hard origin/main
   - Click "Republish" in Replit Deployments UI
5. Verify store_health router: curl https://auto-sem.replit.app/api/v1/store-health/check
6. Verify Klaviyo endpoints: curl https://auto-sem.replit.app/api/v1/klaviyo/diagnose
7. Force a performance sync: curl -X POST https://auto-sem.replit.app/api/v1/automation/force-sync

No code changes needed — this is a deployment task.
```

---

## TASK 1: Fix TikTok /campaigns Endpoint

Paste into Claude Code:
```
Read CLAUDE.md first. The TikTok router at app/routers/tiktok.py is missing a GET /campaigns endpoint — hitting /api/v1/tiktok/campaigns returns 404. A new endpoint was just added but verify it works.

1. Read app/routers/tiktok.py — look for the GET /campaigns endpoint
2. If it exists, verify it:
   - Returns campaign list with status (ACTIVE/PAUSED/DISABLE)
   - Includes per-campaign metrics from report/integrated/get/
   - Returns total_campaigns and active_campaigns counts
3. If it doesn't exist or is broken, add/fix it following the /performance endpoint pattern
4. Test: curl https://auto-sem.replit.app/api/v1/tiktok/campaigns
5. Verify response has the expected structure

Commit with message: "fix(tiktok): verify and fix GET /campaigns endpoint"
```

---

## TASK 2: Conversion Funnel Diagnostic & Fix

Paste into Claude Code:
```
Read CLAUDE.md first. We have 509 ad clicks from Meta with ZERO purchases — there is a severe conversion bottleneck. We need a diagnostic endpoint.

1. Read app/routers/dashboard.py and app/routers/store_health.py
2. Read app/routers/meta.py and app/routers/shopify.py for API patterns
3. Create or update dashboard router to add GET /api/v1/dashboard/conversion-audit:
   - Check Meta Pixel status via Meta API
   - Check if Meta CAPI events are being sent
   - Query Shopify for recent sessions and checkout data
   - Check UTM parameter passthrough on all active Meta ad URLs
   - Measure landing page response time
   - Check for redirect chains and slow load issues
   - Return structured report:
     {
       "funnel": { "ad_clicks": N, "page_views": N, "add_to_carts": N, "checkouts": N, "purchases": N },
       "drop_off_points": [...],
       "pixel_status": "active/missing",
       "landing_page_load_ms": N,
       "utm_tracking": "valid/missing",
       "recommendations": [...]
     }
4. Add UTM validation for all active Meta ad URLs
5. Add Pydantic response models

Commit with message: "feat(dashboard): add conversion-audit endpoint for funnel diagnostics"
```

---

## TASK 3: Shopify Checkout & Cart Recovery Audit

Paste into Claude Code:
```
Read CLAUDE.md first. With 509 clicks and 0 purchases, we need to understand Shopify-side abandonment.

1. Read app/routers/shopify.py for Shopify API integration patterns
2. Create app/services/checkout_audit.py with CheckoutAuditor class:
   - Fetch abandoned checkouts: GET /admin/api/2024-01/checkouts.json?status=open
   - Fetch recent orders: GET /admin/api/2024-01/orders.json?status=any
   - Analyze: total abandoned carts (7d/30d), most abandoned products, abandonment step, device breakdown, avg cart value
   - Cross-reference UTM params on abandoned checkouts with Meta campaign IDs
   - Generate actionable recommendations
3. Add GET /api/v1/shopify/checkout-audit endpoint
4. Add Pydantic models

Commit with message: "feat(shopify): add checkout audit for cart abandonment analysis"
```

---

## TASK 4: Email Capture & Klaviyo Integration Fix

Paste into Claude Code:
```
Read CLAUDE.md first. Klaviyo API key returns "Invalid" — abandoned cart emails are NOT sending. Also no email capture popup on court-sportswear.com.

1. Read app/routers/klaviyo.py and app/services/klaviyo_service.py
2. Fix key resolution: env var -> DB settings table -> clear error log. No hardcoded keys.
3. Add POST /api/v1/klaviyo/install-popup:
   - Generate Klaviyo embedded signup form JS snippet
   - Include popup config: show after 5s, 10% discount offer, exit intent
   - Return snippet + Shopify theme.liquid installation instructions
4. Add POST /api/v1/klaviyo/setup-welcome-flow:
   - Welcome email 1 (immediate): Welcome + 10% discount
   - Welcome email 2 (day 3): Best sellers showcase
   - Welcome email 3 (day 7): Social proof / reviews
5. Add GET /api/v1/klaviyo/check-flow/{flow_id} to verify abandoned cart flow VFSVJd is active

Commit with message: "fix(klaviyo): add key rotation, popup install, and welcome flow setup"
```

---

## TASK 5: Landing Page Optimizer

Paste into Claude Code:
```
Read CLAUDE.md first. 89% of Meta ad traffic is mobile. Audit landing pages for conversion killers.

1. Read app/routers/store_health.py for existing patterns
2. Create app/services/landing_page_optimizer.py:
   - Performance: page load time, response status, redirect chains, page weight
   - Conversion elements (parse HTML): CTA buttons, trust signals, price visibility, social proof, urgency elements
   - Mobile: viewport meta tag, horizontal scroll, tap target sizes, lazy-loaded images
   - Returns scores (0-100) per category with specific recommendations
3. Add GET /api/v1/store-health/landing-page-audit?url=<url>
   Default URL: https://court-sportswear.com/collections/all-mens-t-shirts
4. Add beautifulsoup4 to requirements.txt if missing

Commit with message: "feat(store-health): add landing page audit with mobile and conversion checks"
```

---

## TASK 6: Meta Ad Creative A/B Testing

Paste into Claude Code:
```
Read CLAUDE.md first. Add A/B testing for ad creatives.

1. Read app/routers/meta.py thoroughly
2. Add POST /api/v1/meta/create-test:
   - Accepts: original_ad_id, variant_type (headline/image/cta), variant_value
   - Duplicates ad, modifies variant, splits budget
   - Stores test metadata in DB
3. Add GET /api/v1/meta/test-results:
   - Fetches metrics for original and variant
   - Calculates statistical significance (z-test for CTR)
   - Returns winner/inconclusive with confidence level
4. Add POST /api/v1/meta/auto-optimize:
   - Checks tests with >1000 impressions and >95% confidence
   - Pauses the losing variant automatically
5. Create ab_tests table migration

Commit with message: "feat(meta): add A/B testing with auto-optimization"
```

---

## TASK 7: Google Ads Setup

Paste into Claude Code:
```
Read CLAUDE.md first. Google Ads router exists but returns not_configured.

1. Read app/routers/google_ads.py
2. Implement:
   - POST /api/v1/google/setup: Accept and validate credentials
   - GET /api/v1/google/campaigns: List campaigns with metrics
   - POST /api/v1/google/campaigns: Create Shopping campaign
   - POST /api/v1/google/generate-feed: Generate Google Shopping feed from Shopify products
   - GET /api/v1/google/performance: Fetch campaign metrics
3. Add google-ads>=23.0.0 to requirements.txt
4. Add sync job to scheduler (every 6h)

Commit with message: "feat(google): implement Google Ads with Shopping campaigns and product feed"
```

---

## TASK 8: Revenue Attribution Pipeline

Paste into Claude Code:
```
Read CLAUDE.md first. No way to connect Meta click to Shopify purchase = can't calculate true ROAS.

1. Read app/database.py for model patterns
2. Create attribution_events table: id, session_id, event_type (ad_click/page_view/add_to_cart/checkout_start/purchase), source_platform, campaign_id, ad_id, shopify_order_id, revenue, ad_spend, utm params, created_at
3. Create app/services/attribution.py:
   - record_event(), link_session(), get_funnel(), get_roas()
   - Match UTM params to campaigns
4. Extend Shopify orders webhook to record purchase attribution events
5. Add GET /api/v1/dashboard/attribution: full funnel per campaign with ROAS

Commit with message: "feat(attribution): add revenue attribution pipeline with full funnel tracking"
```

---

## TASK 9: Automated Daily Report

Paste into Claude Code:
```
Read CLAUDE.md first. Need daily performance email so we don't have to check the dashboard manually.

1. Read scheduler.py for job patterns
2. Create app/services/daily_report.py:
   - Gather yesterday's metrics from Meta, TikTok, Google, Shopify
   - Compare day-over-day and vs 7-day rolling average
   - Flag >20% changes as alerts
   - Identify top 3 and bottom 3 ads
   - Generate responsive HTML email
   - Send via Klaviyo transactional API or SMTP fallback
3. Add GET /api/v1/dashboard/daily-report (preview)
4. Add POST /api/v1/dashboard/send-report (send immediately)
5. Register scheduler job: daily at 08:00 UTC

Commit with message: "feat(reports): add automated daily performance report with email delivery"
```

---

## TASK 10: Fix sync_data.py Broken URLs

Paste into Claude Code:
```
Read CLAUDE.md first. sync_data.py has broken URLs missing /v1 in API paths.

1. Read sync_data.py
2. Fix all API paths to include /api/v1/ prefix
3. Verify base URL is correct (https://auto-sem.replit.app)
4. Verify all referenced endpoints actually exist
5. Add retry logic (3 attempts, exponential backoff)
6. Add --dry-run flag
7. Add error handling that continues on failure

Commit with message: "fix(sync): correct API paths and add retry logic"
```

---

## TASK 11: CI/CD & Testing

Paste into Claude Code:
```
Read CLAUDE.md first. No test framework exists. Add basic tests and CI.

1. Add to requirements.txt: pytest>=7.4.0, pytest-asyncio>=0.21.0, httpx>=0.24.0, pytest-cov>=4.1.0
2. Create tests/ directory with conftest.py:
   - Test FastAPI client using httpx.AsyncClient
   - Mock external APIs (Meta, TikTok, Shopify, Klaviyo)
   - Test database fixtures
3. Write tests:
   - test_health.py: /health returns 200, all routers respond
   - test_meta.py: campaign list, performance metrics (mocked)
   - test_optimizer.py: budget rules, bid adjustment, min/max bounds
   - test_dashboard.py: overview aggregation, date filtering
4. Create .github/workflows/test.yml: Python 3.11, pip install, pytest with coverage
5. Create scripts/smoke_test.py: hit /health + 5 critical endpoints, exit 0/1

Commit with message: "feat(testing): add pytest framework, API tests, and GitHub Actions CI"
```

---

## Execution Notes

- **Run tasks 0-5 first** — they directly address the 0-conversion revenue problem
- Task 0 (deploy) MUST be done first to get v2.5.0 live
- Tasks 6-9 build growth infrastructure
- Tasks 10-11 fix technical debt
- Each task is independent and can be pasted into Claude Code in Git Bash
- After each task, verify changes via the relevant API endpoints
- The Replit deploy flow: push to GitHub → curl deploy/pull endpoint → Republish in Replit UI
