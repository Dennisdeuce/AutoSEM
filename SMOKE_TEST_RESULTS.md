# AutoSEM Production Smoke Test Results

**Date:** 2026-02-20
**Target:** https://auto-sem.replit.app
**Live Version:** 1.9.0 (local code: 2.2.0)
**Routers Loaded:** 12/13 (automation FAILED to load)

## Summary

| Category | Pass | Fail | Skip |
|----------|------|------|------|
| Root/Health | 5 | 0 | 0 |
| Dashboard | 7 | 0 | 2 |
| Meta | 4 | 0 | 0 |
| Campaigns | 3 | 0 | 0 |
| Products | 2 | 0 | 0 |
| Settings | 1 | 0 | 0 |
| Klaviyo | 5 | 0 | 0 |
| Shopify | 7 | 2 | 0 |
| TikTok | 9 | 0 | 0 |
| Google Ads | 2 | 0 | 0 |
| SEO | 2 | 0 | 0 |
| Deploy | 2 | 0 | 0 |
| Health Router | 2 | 0 | 0 |
| Automation | 0 | 1 | 0 |
| **Total** | **51** | **3** | **2** |

## Bugs Found & Fixed

### BUG-7: Automation router fails to load (FIXED)
- **Cause:** `app/routers/automation.py` line 216 uses `Query` from FastAPI but does not import it
- **Impact:** All 9 automation endpoints return 404 (router never registers)
- **Fix:** Added `Query` to the import: `from fastapi import APIRouter, Depends, BackgroundTasks, Query`
- **Status:** Fixed in local code, pending deploy

### BUG-8: Shopify /products/{id} returns 500 for invalid IDs
- **Cause:** Shopify API returns 404 for non-existent product IDs, but the endpoint doesn't handle this gracefully
- **Impact:** 500 Internal Server Error instead of a clean error response
- **Severity:** Low (only affects invalid product ID lookups)

### BUG-9: Shopify /collections/{id}/products returns 500 for invalid IDs
- **Cause:** Same as BUG-8 — no graceful handling of Shopify API errors
- **Impact:** 500 Internal Server Error
- **Severity:** Low

## Detailed Results

### Root & System Endpoints
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/` | GET | 200 PASS | Returns version, routers list |
| `/health` | GET | 200 PASS | Confirms 12/13 routers loaded |
| `/version` | GET | 200 PASS | Returns `1.9.0` |
| `/docs` | GET | 200 PASS | Swagger UI loads |
| `/dashboard` | GET | 200 PASS | HTML dashboard template |

### Dashboard Router (`/api/v1/dashboard`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Aggregated metrics with Meta + TikTok |
| `/activity` | GET | 200 PASS | Recent activity log |
| `/meta-performance` | GET | 200 PASS | 7-day Meta insights |
| `/pause-all` | POST | 200 PASS | Emergency pause (tested) |
| `/resume-all` | POST | 200 PASS | Resume all (tested) |
| `/log-activity` | POST | 200 PASS | Activity logging works |
| `/sync-meta` | POST | 200 PASS | Meta sync working |
| `/fix-data` | POST | 200 PASS | Data fix working |
| `/optimize-now` | POST | SKIP | Added in v2.0.0 (not deployed) |
| `/sync-performance` | POST | SKIP | Added in v2.0.0 (not deployed) |

### Meta Router (`/api/v1/meta`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Token valid, ad account connected |
| `/campaigns` | GET | 200 PASS | Returns 2 campaigns (1 ACTIVE, 1 PAUSED) |
| `/connect` | GET | 307 PASS | Redirects to OAuth (expected) |
| `/set-budget` | POST | 422 PASS | Validation error without proper body (expected) |

### Campaigns Router (`/api/v1/campaigns`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/` | GET | 200 PASS | 307 redirect to trailing slash, then 200 |
| `/active` | GET | 200 PASS | Returns active campaigns |
| `/` | POST | 200 PASS | Campaign creation works |

### Products Router (`/api/v1/products`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/` | GET | 200 PASS | 307 redirect to trailing slash, then 200 |
| `/{id}` | GET | 200 PASS | Single product lookup |

### Settings Router (`/api/v1/settings`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/` | GET | 200 PASS | Returns all settings |

### Klaviyo Router (`/api/v1/klaviyo`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | API key loaded, connected |
| `/flows` | GET | 200 PASS | Lists Klaviyo flows |
| `/metrics` | GET | 200 PASS | Email performance metrics |
| `/profiles` | GET | 200 PASS | Lists subscribers |
| `/trigger-flow` | POST | 200 PASS | Event trigger works |

### Shopify Router (`/api/v1/shopify`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Store connected |
| `/products` | GET | 200 PASS | Products listed |
| `/customers` | GET | 200 PASS | Customer data |
| `/collections` | GET | 200 PASS | Collections listed |
| `/health-check` | GET | 200 PASS | Full store audit |
| `/blog-posts` | GET | 200 PASS | Blog posts listed |
| `/webhooks` | GET | 200 PASS | Registered webhooks |
| `/products/1` | GET | 500 FAIL | Invalid ID causes 500 (BUG-8) |
| `/collections/1/products` | GET | 500 FAIL | Invalid ID causes 500 (BUG-9) |

### TikTok Router (`/api/v1/tiktok`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Connected |
| `/performance` | GET | 200 PASS | Performance data |
| `/targeting-categories` | GET | 200 PASS | Interest categories |
| `/targeting-keywords` | GET | 200 PASS | Keyword search |
| `/images` | GET | 200 PASS | Uploaded images |
| `/videos` | GET | 200 PASS | Uploaded videos |
| `/identities` | GET | 200 PASS | TikTok identities |
| `/debug-ffmpeg` | GET | 200 PASS | ffmpeg check |
| `/advertiser-info` | GET | 200 PASS | Advertiser details |

### Google Ads Router (`/api/v1/google`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Returns not_configured (expected) |
| `/campaigns` | GET | 200 PASS | Empty campaign list (no credentials) |

### SEO Router (`/api/v1/seo`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/all-jsonld` | GET | 200 PASS | All product structured data |
| `/sitemap.xml` | GET | 200 PASS | XML sitemap generated |

### Deploy Router (`/api/v1/deploy`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 200 PASS | Deploy status |
| `/pull` | POST | 200 PASS | Deploy pull with auth key |

### Health Router (`/api/v1/health`)
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/deep` | GET | 200 PASS | Deep health check |
| `/reset-db` | GET | 200 PASS | DB error recovery |

### Automation Router (`/api/v1/automation`) - NOT LOADED
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/status` | GET | 404 FAIL | Router failed to import (BUG-7: missing Query import) |

## Notes

- Live site is at v1.9.0 while local code is v2.2.0. Phase 10 endpoints (optimize-now, sync-performance, ad creative CRUD) not yet deployed.
- 307 redirects on `/campaigns`, `/products`, `/settings` are normal FastAPI trailing-slash behavior.
- POST endpoints on Replit require `Content-Length: 0` header when no body is sent (411 otherwise).
- Shopify 500s on invalid IDs are low-severity but should be wrapped in try/except with proper error responses.
