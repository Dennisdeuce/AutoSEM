"""TikTok Campaigns endpoint — supplements tiktok.py with GET /campaigns.

This router is mounted at the same /api/v1/tiktok prefix as the main
TikTok router, adding the missing /campaigns endpoint that the dashboard
expects. Imports shared helpers from tiktok.py.

Fixes BUG-12: GET /api/v1/tiktok/campaigns was returning 404.
"""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger("AutoSEM.TikTokCampaigns")
router = APIRouter()


def _get_tiktok_helpers():
    """Lazy import helpers from the main tiktok router to avoid circular imports."""
    from app.routers.tiktok import _get_active_token, _tiktok_api, _safe_get_data
    return _get_active_token, _tiktok_api, _safe_get_data


@router.get("/campaigns", summary="List TikTok campaigns with metrics")
def get_tiktok_campaigns(db: Session = Depends(get_db)):
    """List all TikTok campaigns with their status and 7-day performance metrics.

    Returns:
        campaigns: List of campaign objects with metadata + metrics
        total_campaigns: Total campaign count
        active_campaigns: Count of ENABLE/ACTIVE campaigns
    """
    _get_active_token, _tiktok_api, _safe_get_data = _get_tiktok_helpers()

    creds = _get_active_token(db)
    if not creds.get("access_token") or not creds.get("advertiser_id"):
        return JSONResponse(status_code=200, content={
            "campaigns": [],
            "total_campaigns": 0,
            "active_campaigns": 0,
            "error": "TikTok not connected — no access token or advertiser ID",
        })

    try:
        # --- Fetch campaign list ---
        result = _tiktok_api(
            "GET", "/campaign/get/", creds["access_token"],
            params={
                "advertiser_id": creds["advertiser_id"],
                "page_size": 100,
            },
        )
        campaigns_raw = []
        if result.get("code") == 0:
            data = _safe_get_data(result)
            campaigns_raw = data.get("list", [])

        # --- Fetch 7-day performance metrics per campaign ---
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        campaign_metrics = {}
        try:
            stats = _tiktok_api(
                "GET", "/report/integrated/get/", creds["access_token"],
                params={
                    "advertiser_id": creds["advertiser_id"],
                    "report_type": "BASIC",
                    "dimensions": json.dumps(["campaign_id"]),
                    "data_level": "AUCTION_CAMPAIGN",
                    "start_date": start_date,
                    "end_date": end_date,
                    "metrics": json.dumps([
                        "spend", "impressions", "clicks", "ctr", "cpc",
                        "reach", "conversion", "cost_per_conversion",
                    ]),
                },
            )
            if stats.get("code") == 0:
                stats_data = _safe_get_data(stats)
                for row in stats_data.get("list", []):
                    dims = row.get("dimensions", {})
                    m = row.get("metrics", {})
                    cid = str(dims.get("campaign_id", ""))
                    if cid:
                        campaign_metrics[cid] = {
                            "spend": round(float(m.get("spend", 0)), 2),
                            "impressions": int(float(m.get("impressions", 0))),
                            "clicks": int(float(m.get("clicks", 0))),
                            "ctr": round(float(m.get("ctr", 0)) * 100, 2),
                            "cpc": round(float(m.get("cpc", 0)), 2),
                            "reach": int(float(m.get("reach", 0))),
                            "conversions": int(float(m.get("conversion", 0))),
                            "cost_per_conversion": round(
                                float(m.get("cost_per_conversion", 0)), 2
                            ),
                        }
        except Exception as stats_err:
            logger.warning(f"Could not fetch TikTok campaign metrics: {stats_err}")

        # --- Merge campaign info with metrics ---
        campaigns = []
        active_count = 0
        for c in campaigns_raw:
            cid = str(c.get("campaign_id", ""))
            status = c.get("operation_status", c.get("status", "UNKNOWN"))
            metrics = campaign_metrics.get(cid, {})

            if status in ("ENABLE", "ACTIVE", "CAMPAIGN_STATUS_ENABLE"):
                active_count += 1

            campaigns.append({
                "campaign_id": cid,
                "campaign_name": c.get("campaign_name", ""),
                "status": status,
                "budget": c.get("budget", 0),
                "budget_mode": c.get("budget_mode", ""),
                "objective_type": c.get("objective_type", ""),
                "spend": metrics.get("spend", 0),
                "impressions": metrics.get("impressions", 0),
                "clicks": metrics.get("clicks", 0),
                "ctr": metrics.get("ctr", 0),
                "cpc": metrics.get("cpc", 0),
                "reach": metrics.get("reach", 0),
                "conversions": metrics.get("conversions", 0),
                "cost_per_conversion": metrics.get("cost_per_conversion", 0),
            })

        # Sort by spend descending (highest spenders first)
        campaigns.sort(key=lambda x: x["spend"], reverse=True)

        return {
            "campaigns": campaigns,
            "total_campaigns": len(campaigns),
            "active_campaigns": active_count,
        }

    except Exception as e:
        logger.error(f"TikTok campaigns error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={
            "campaigns": [],
            "total_campaigns": 0,
            "active_campaigns": 0,
            "error": str(e),
        })
