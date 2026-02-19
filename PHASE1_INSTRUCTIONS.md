# PHASE 1 — Fix the Engine (Critical Path)

Goal: Make the optimization loop actually work. After these fixes, AutoSEM can read real performance data, make real optimization decisions, and execute them against Meta Ads — automatically, on a schedule.

**CRITICAL: Do NOT break the existing dashboard or API endpoints.**

---

## Bug 1: Constructor mismatches in automation.py

**File:** `app/routers/automation.py`

`CampaignOptimizer()` and `CampaignGenerator()` are called without the required `db` argument in `run_automation_cycle()`, `run_optimization()`, and `create_campaigns()`.

**Fix:** Change every `CampaignOptimizer()` to `CampaignOptimizer(db)` and every `CampaignGenerator()` to `CampaignGenerator(db)`.

---

## Bug 2: Build real performance sync service

**File:** Create `app/services/performance_sync.py` (NEW FILE)

The `sync-performance` endpoint calls `google_ads.sync_performance(db)` which doesn't exist. Need a real service that:
- Pulls live data from Meta (use MetaAdsService().get_performance())
- Pulls TikTok performance (use existing TikTok endpoints)
- Writes impressions, clicks, spend, conversions, revenue back to matching CampaignModel records
- Discovers & links real Meta campaigns that have no local CampaignModel record (match by platform_campaign_id)
- The 2 real Meta campaigns are: `120241759616260364` (Sales) and `120206746647300364` (Ongoing)

**Then update** `app/routers/automation.py` sync-performance endpoint to use `PerformanceSyncService(db).sync_all()` instead of broken `google_ads.sync_performance(db)`.

---

## Bug 3: Wire up the scheduler in main.py

**File:** `main.py`

`scheduler.py` exists with `start_scheduler()` function but it's never called. The 6h optimization and 2h sync jobs never execute.

**Fix:** In `create_app()`, after all routers are registered:
```python
from scheduler import start_scheduler, stop_scheduler
start_scheduler()

@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()
```

---

## Bug 4: Fix scheduler URL paths

**File:** `scheduler.py`

Both `run_optimization_cycle()` and `sync_performance()` call `/api/automation/` but routes are at `/api/v1/automation/`.

**Fix:** Change:
- `/api/automation/run-cycle` → `/api/v1/automation/run-cycle`
- `/api/automation/sync-performance` → `/api/v1/automation/sync-performance`

---

## Bug 5: Add appsecret_proof to Meta service

**File:** `app/services/meta_ads.py`

All Meta Graph API calls need HMAC-SHA256 appsecret_proof. Without it, campaign creation and management calls fail.

**Fix:** Add method:
```python
import hashlib, hmac

def _compute_appsecret_proof(self) -> str:
    return hmac.new(
        self.app_secret.encode('utf-8'),
        self.access_token.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
```

Include `appsecret_proof` parameter in ALL Graph API calls (create_campaign, pause_campaign, enable_campaign, update_campaign_budget, get_performance, get_account_info, refresh_access_token).

---

## Bug 6: Add Shopify order webhook for revenue tracking

**File:** `app/routers/shopify.py`

No revenue tracking exists. CampaignModel.total_revenue is always 0.0, making ROAS permanently 0 and the optimizer blind.

**Fix:** Add `POST /api/v1/shopify/webhook/order-created` endpoint that:
- Receives Shopify order webhook payload
- Extracts order total, UTM params from landing_site/referring_site
- Attributes revenue to the correct campaign via UTM matching
- Updates CampaignModel.total_revenue

Register the webhook with Shopify Admin API during app startup or via a setup endpoint.

---

## Bug 7: Google Ads credentials validation

**File:** `app/services/google_ads.py`

Google Ads has no credentials configured (all empty strings). All operations fall to `_simulate_create`. The 81 phantom campaigns have been archived in the DB already, but the service needs proper handling.

**Fix:** Add `is_configured` property check that returns False when credentials are empty. Ensure all methods gracefully handle unconfigured state without simulation — just return `{"status": "not_configured", "message": "Google Ads credentials not set"}`.

---

## Execution Order

1. Bug 1 (constructor fix) — unblocks optimization
2. Bug 2 (performance sync) — unblocks data flow
3. Bug 3 + Bug 4 (scheduler) — enables automation
4. Bug 5 (appsecret_proof) — enables Meta write operations
5. Bug 6 (Shopify webhook) — enables revenue tracking
6. Bug 7 (Google Ads cleanup) — prevents false data

## After All Fixes

```bash
git add -A && git commit -m "Phase 1: Fix optimization engine - 7 critical bugs" && git push origin main
```

Then notify that the push is ready for deploy webhook + Replit redeploy.
