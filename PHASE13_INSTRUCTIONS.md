# AutoSEM Phase 13: Revenue Pipeline Fix

## Context
AutoSEM v2.4.0 is live but generating ZERO revenue. Meta ads perform well ($0.12 CPC, 4.3% CTR, 453 clicks) but the conversion pipeline is broken. This phase fixes the technical debt preventing revenue.

## Task 1: Fix Klaviyo Key Management (CRITICAL)
The Klaviyo integration returns "Invalid API key" — the hardcoded fallback key is stale/revoked.

**Files:** `app/routers/klaviyo.py`, `app/services/klaviyo_service.py`

**Requirements:**
1. Remove the hardcoded `KLAVIYO_FALLBACK_KEY` — hardcoded keys rot. Key should ONLY come from env var or DB.
2. Add a `/klaviyo/validate-key` POST endpoint that accepts `{"api_key": "..."}`, tests it against `GET https://a.klaviyo.com/api/accounts/` with header `Authorization: Klaviyo-API-Key {key}` and `revision: 2024-10-15`, and if valid saves to DB, if invalid returns error.
3. Integrate Klaviyo status into `/health` endpoint — report Klaviyo connected/disconnected/invalid_key status.
4. Add retry logic with exponential backoff (3 attempts) on all Klaviyo API calls in `_klaviyo_request`.
5. Add a `/klaviyo/diagnose` GET endpoint that returns: current key source (env/db/none), key prefix (first 8 chars masked), last successful API call timestamp (store in module-level var), and last error message.
6. Cache `/klaviyo/status` results for 60s to avoid API hammering.

## Task 2: Add Conversion Funnel Tracking (HIGH)
The dashboard needs the full funnel: impressions → clicks → landing pages → product views → purchases.

**Files:** `app/routers/dashboard.py`, `templates/dashboard.html`

**Requirements:**
1. Add `GET /dashboard/funnel` endpoint that returns funnel data:
   - Pull Meta insights: impressions, clicks, ctr, cpc, landing_page_views (already available via Meta campaign insights API, use existing Meta API call patterns from `app/routers/meta.py`)
   - Pull Shopify order count and revenue from `/api/v1/shopify/orders` or direct Shopify API
   - Calculate drop-off percentages between each stage
2. Add a "Revenue Pipeline" section to the dashboard HTML showing the funnel visually with drop-off rates.
3. When purchases = 0 but clicks > 100, display a prominent warning with checklist: "Reviews installed? Email capture active? Collection page deep-links? Mobile UX tested?"

## Task 3: Add Scheduler Resilience (HIGH)
Performance sync had a 2-day gap. Scheduled jobs need retry logic.

**Files:** `scheduler.py`

**Requirements:**
1. Wrap each scheduled job execution in try/except with 3 retry attempts and exponential backoff (5s, 15s, 45s).
2. Track `last_successful_sync` as a module-level dict keyed by job name, with timestamps.
3. Add `GET /health/scheduler` endpoint (add to health router) reporting: jobs registered (count), last run time per job, failed jobs in last 24h.
4. If `sync_performance` fails 3x consecutively, create an activity log entry with action `SYNC_FAILURE_CRITICAL`.
5. Add `POST /automation/force-sync` endpoint that runs performance sync immediately with verbose JSON output.

## Task 4: Add Store Health Monitor (MEDIUM)
AutoSEM should proactively check the store for conversion-blocking issues.

**Files:** New `app/routers/store_health.py`, register in `main.py`

**Requirements:**
1. `GET /store-health/check` runs these checks against `https://court-sportswear.com`:
   - Homepage response time < 3s (use `requests` with timeout tracking)
   - `/collections/all-mens-t-shirts` returns HTTP 200
   - Page source contains `judge` or `jdgm` (Judge.me reviews widget)
   - Page source contains `fbq` (Meta Pixel)
   - Page source contains `free shipping` (case-insensitive)
   - Page source contains `klaviyo` (email capture)
   - SSL certificate valid (requests doesn't throw SSLError)
2. Return JSON: `{"status": "ok", "score": "5/7", "checks": [{"name": "...", "passed": true/false, "detail": "..."}]}`
3. Register router with prefix `/api/v1/store-health` and tag `store-health`.

## Task 5: Smarter Pre-Revenue Optimizer (MEDIUM)
The optimizer in awareness mode is too passive. It should actively recommend actions.

**Files:** `app/routers/automation.py`

**Requirements:**
1. In the optimize endpoint, when 0 conversions after $50+ total spend, generate structured recommendations as a list of strings.
2. Store recommendations in activity_log with action `OPTIMIZER_RECOMMENDATION`.
3. Add `GET /automation/recommendations` that returns the last 10 recommendations from activity_log filtered by action type.
4. When revenue > 0 appears for the first time in a sync, auto-log celebration activity and add recommendation to set `min_roas_threshold` back to 1.5.

## Task 6: Daily Performance Snapshots (MEDIUM)
Store daily metrics for trend analysis.

**Files:** `app/database.py` (add model), `scheduler.py`, `app/routers/dashboard.py`

**Requirements:**
1. Add `PerformanceSnapshot` model to database.py: columns = id (int PK), date (Date), platform (String), campaign_id (String nullable), spend (Float), clicks (Int), impressions (Int), ctr (Float), cpc (Float), conversions (Int default 0), revenue (Float default 0). Add `Base.metadata.create_all()` call to pick it up.
2. Add a daily snapshot function to scheduler.py that runs after the midnight optimization. It queries current campaign data and inserts one row per campaign.
3. Add `GET /dashboard/trends?days=30` that returns daily aggregated metrics (sum spend, sum clicks, etc.) grouped by date.
4. Add `GET /dashboard/trends/{campaign_id}?days=30` for per-campaign trends.

## Task 7: Update CLAUDE.md
After all changes:
- Bump version to 2.5.0 in `app/version.py`
- Update CLAUDE.md with:
  - Version 2.5.0
  - New routers: store_health
  - New endpoints documented
  - Scheduler improvements documented  
  - Phase 13 added to history
  - Known bugs: BUG-11 Klaviyo fallback key was hardcoded and expired (fixed)

## Execution Order
Tasks 1 → 3 → 4 → 2 → 5 → 6 → 7

## Deploy
```bash
git add -A && git commit -m "Phase 13: Revenue pipeline fixes v2.5.0"
git push origin main
```

## Critical Rules
- Do NOT break existing endpoints — all 51/54 smoke tests must still pass
- Do NOT modify Meta API call patterns — graph.facebook.com access goes through AutoSEM proxy
- Do NOT change existing column names/types in DB — only ADD new columns/tables
- All new endpoints MUST return JSON with a `status` field
- Test each router import after changes (python -c "from app.routers.klaviyo import router")
- Meta budgets are in cents (2500 = $25/day)
