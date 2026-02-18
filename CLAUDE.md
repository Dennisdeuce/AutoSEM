# CLAUDE.md — AutoSEM

## Project Overview

AutoSEM is an autonomous SEM (Search Engine Marketing) platform built with FastAPI. It integrates with Meta Ads, TikTok Ads, Google Ads, and Shopify to automate campaign creation, management, and optimization for Court Sportswear.

## Commands

```bash
# Run locally (Replit uses main.py directly)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Live API
https://auto-sem.replit.app
https://auto-sem.replit.app/docs     # Swagger UI
https://auto-sem.replit.app/openapi.json
```

No test framework configured. Use `/docs` Swagger UI for manual testing.

## Architecture

**FastAPI** app (`main.py`) with 8 routers under `/api/v1/`:

| Router | Purpose |
|--------|---------|
| `dashboard` | Aggregated metrics, emergency pause/resume, activity log |
| `meta` | Meta/Facebook OAuth, token management, campaign performance |
| `tiktok` | TikTok OAuth, campaign launch, video generation, targeting |
| `campaigns` | CRUD for campaign records in local DB |
| `products` | Shopify product sync and management |
| `automation` | Optimization engine, scheduled cycles, performance sync |
| `settings` | Spend limits, ROAS thresholds, emergency pause config |
| `deploy` | GitHub webhook for auto-pull on push to main |

**Database:** SQLAlchemy with PostgreSQL (tables: products, campaigns, meta_tokens, tiktok_tokens, activity_logs, settings)

**Scheduler** (`scheduler.py`): APScheduler runs optimization every 6h, performance sync every 2h.

## Key Files

- `main.py` — FastAPI app factory, router registration, static files
- `app/routers/` — All 8 API router modules
- `app/services/` — Business logic (meta_ads, google_ads, optimizer, campaign_generator)
- `app/database.py` — SQLAlchemy models and session management
- `app/schemas.py` — Pydantic request/response models
- `scheduler.py` — Background task scheduling
- `templates/` — Jinja2 HTML templates for dashboard UI

## Integrations

- **Shopify** (Court Sportswear: `4448da-3.myshopify.com`) — product sync
- **Meta Ads** (ad account: `act_1358540228396119`, app: `909757658089305`) — campaign management
- **TikTok Ads** — campaign creation with video generation
- **Google Ads** — campaign management (Phase 2)

## Tools & Resources

### Shopify Admin API

Token expires every 24h. Always generate fresh:
```bash
curl -s -X POST "https://4448da-3.myshopify.com/admin/oauth/access_token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=$SHOPIFY_CLIENT_ID&client_secret=$SHOPIFY_CLIENT_SECRET&grant_type=client_credentials"
```
Client ID and secret are stored in Replit Secrets as `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET`.

### Meta Graph API

Requires `appsecret_proof` (HMAC-SHA256 of token with app secret):
```bash
TOKEN="<meta_access_token>"
APP_SECRET="$META_APP_SECRET"
PROOF=$(echo -n "$TOKEN" | openssl dgst -sha256 -hmac "$APP_SECRET" | awk '{print $2}')
curl "https://graph.facebook.com/v19.0/act_1358540228396119/campaigns?fields=id,name,status&access_token=$TOKEN&appsecret_proof=$PROOF"
```

### Deploy Webhook

```bash
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"
```

**Important — Replit does NOT auto-restart after `deploy/pull`.** The webhook pulls
new code to disk, but the running process keeps serving the old code. After triggering
a deploy, you must **manually republish** in the Replit UI (Deployments tab → Redeploy)
for changes to take effect.

**Chicken-and-egg on first deploy:** If Replit's workspace has no `.git` directory,
the old deploy.py fails silently. The fixed version (commit `160d766`) initializes
the git repo automatically, but it must be deployed manually the first time via
Replit's UI to bootstrap itself.

### Meta Campaign Management Endpoints

Available in repo (`app/routers/meta.py`) but require deploy to Replit:

| Method | Endpoint | Body |
|--------|----------|------|
| GET | `/api/v1/meta/status` | — |
| GET | `/api/v1/meta/campaigns` | — |
| POST | `/api/v1/meta/activate-campaign` | `{"campaign_id": "..."}` |
| POST | `/api/v1/meta/pause-campaign` | `{"campaign_id": "..."}` |
| POST | `/api/v1/meta/set-budget` | `{"campaign_id": "...", "daily_budget": 1500}` |

Currently live on Replit: only `status`, `connect`, `callback`, `refresh`.
Campaign management endpoints (`activate`, `pause`, `set-budget`, `campaigns`) need
a Replit redeploy to go live.

## Environment Variables

See Replit Secrets. Key vars: `DATABASE_URL`, `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_AD_ACCOUNT_ID`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_ADVERTISER_ID`, `SHOPIFY_STORE_URL`, `SHOPIFY_ACCESS_TOKEN`, `DEPLOY_KEY`.

## Key Conventions

- All routers prefixed `/api/v1/<name>`
- Platform tokens stored in DB (meta_tokens, tiktok_tokens tables)
- Graceful error handling — endpoints return `{"success": false, "error": "..."}` on failure
- GitHub repo: `https://github.com/Dennisdeuce/AutoSEM` (branch: main)
- Deployed on Replit — workspace may not be a git repo (deploy.py handles this)
