# AutoSEM Phase 1: Fix the Optimization Engine

Read through the codebase first, then fix these bugs IN ORDER. Do NOT break any existing working endpoints or the dashboard.

## Bug 1: Constructor mismatches crash the optimizer

File: app/routers/automation.py

- run_automation_cycle() calls CampaignOptimizer() and CampaignGenerator() with no args
- Both classes require db: Session in __init__
- Fix: pass db to both constructors in run_automation_cycle(), run_optimization(), and create_campaigns()

## Bug 2: sync-performance calls non-existent method

File: app/routers/automation.py

- sync_performance() calls google_ads.sync_performance(db) which doesn't exist
- Create a new file: app/services/performance_sync.py
- It should pull live data from Meta (use the meta_ads.py get_performance() method) and TikTok
- Write impressions, clicks, spend, conversions, revenue to matching CampaignModel records
- Also: discover real Meta campaigns that have no local CampaignModel record and create them
- The 2 real Meta campaigns are: 120241759616260364 (Sales - PAUSED) and 120206746647300364 (Ongoing - ACTIVE)
- Update the sync-performance endpoint to use the new PerformanceSyncService

## Bug 3: Clean phantom Google Ads campaigns

- There are 45 CampaignModel records with platform='google_ads' and platform_campaign_id=NULL
- These were never pushed to Google. Mark them all as status='draft' so the optimizer ignores them
- Add a cleanup function that runs on startup or first sync

## Bug 4: Scheduler never starts

File: main.py

- Import start_scheduler from scheduler.py and call it after app creation
- Add shutdown event to call stop_scheduler()

## Bug 5: Scheduler URL paths are wrong

File: scheduler.py

- Change /api/automation/run-cycle to /api/v1/automation/run-cycle
- Change /api/automation/sync-performance to /api/v1/automation/sync-performance

## Bug 6: Add appsecret_proof to Meta service

File: app/services/meta_ads.py

- All Graph API calls need HMAC-SHA256 of access_token with app_secret as appsecret_proof parameter
- Add a _compute_proof() method and include it in every API request

## Bug 7: Add Shopify order webhook for revenue tracking

File: app/routers/shopify.py

- Add POST /api/v1/shopify/webhook/order-created endpoint
- When an order comes in, extract UTM/referrer to attribute revenue to the correct campaign
- Update CampaignModel.total_revenue

## After all fixes

Commit and push to GitHub with a clear commit message. Do NOT attempt to deploy to Replit - that requires manual steps handled separately.
