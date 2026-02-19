"""
Google Ads router - Campaign Management
Wraps GoogleAdsService for HTTP access.
"""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, ActivityLogModel
from app.services.google_ads import GoogleAdsService

logger = logging.getLogger("AutoSEM.GoogleAds")
router = APIRouter()

service = GoogleAdsService()


def _log_activity(db: Session, action: str, entity_id: str = None, details: str = None):
    """Log an activity entry."""
    try:
        log = ActivityLogModel(
            action=action,
            entity_type="campaign",
            entity_id=entity_id or "",
            details=details or "",
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ─── Request Models ──────────────────────────────────────────────

class CampaignActionRequest(BaseModel):
    campaign_id: str


class SetBudgetRequest(BaseModel):
    campaign_id: str
    daily_budget: float  # Budget in dollars (e.g., 15.00)


class CreateCampaignRequest(BaseModel):
    campaign_name: str
    daily_budget: float = 10.0
    target_roas: float = 1.5


# ─── Endpoints ───────────────────────────────────────────────────

@router.get("/status", summary="Check Google Ads status",
            description="Check if Google Ads credentials are configured and test connectivity")
def google_ads_status():
    return {
        "status": "ok" if service.is_configured else "not_configured",
        "configured": service.is_configured,
        "customer_id": service.customer_id or None,
        "message": "Google Ads credentials configured" if service.is_configured else "Missing GOOGLE_ADS_CUSTOMER_ID or GOOGLE_ADS_DEVELOPER_TOKEN",
    }


@router.get("/campaigns", summary="List Google Ads campaigns",
            description="Get all campaigns with performance metrics")
def list_campaigns(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    try:
        campaigns = service.get_performance(days=days)
        return {
            "status": "ok",
            "count": len(campaigns),
            "days": days,
            "campaigns": campaigns,
        }
    except Exception as e:
        logger.error(f"Failed to list campaigns: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/activate-campaign", summary="Activate a Google Ads campaign",
             description="Enable a campaign via Google Ads API")
def activate_campaign(req: CampaignActionRequest, db: Session = Depends(get_db)):
    try:
        result = service.enable_campaign(req.campaign_id)
        if result.get("success"):
            _log_activity(db, "GOOGLE_CAMPAIGN_ACTIVATED", req.campaign_id,
                         f"Campaign {req.campaign_id} activated via API")
            logger.info(f"Google Ads campaign {req.campaign_id} activated")
            return {
                "status": "activated",
                "campaign_id": req.campaign_id,
                "simulated": result.get("simulated", False),
            }
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Failed to activate campaign: {error_msg}")
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": error_msg,
            }
    except Exception as e:
        logger.error(f"Exception activating campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/pause-campaign", summary="Pause a Google Ads campaign",
             description="Pause a campaign via Google Ads API")
def pause_campaign(req: CampaignActionRequest, db: Session = Depends(get_db)):
    try:
        result = service.pause_campaign(req.campaign_id)
        if result.get("success"):
            _log_activity(db, "GOOGLE_CAMPAIGN_PAUSED", req.campaign_id,
                         f"Campaign {req.campaign_id} paused via API")
            logger.info(f"Google Ads campaign {req.campaign_id} paused")
            return {
                "status": "paused",
                "campaign_id": req.campaign_id,
                "simulated": result.get("simulated", False),
            }
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Failed to pause campaign: {error_msg}")
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": error_msg,
            }
    except Exception as e:
        logger.error(f"Exception pausing campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/set-budget", summary="Set campaign daily budget",
             description="Update daily budget on a Google Ads campaign (in dollars)")
def set_campaign_budget(req: SetBudgetRequest, db: Session = Depends(get_db)):
    try:
        result = service.update_campaign_budget(req.campaign_id, req.daily_budget)
        if result.get("success"):
            _log_activity(db, "GOOGLE_BUDGET_SET", req.campaign_id,
                         f"Budget set to ${req.daily_budget:.2f}/day")
            return {
                "status": "updated",
                "campaign_id": req.campaign_id,
                "daily_budget": req.daily_budget,
                "simulated": result.get("simulated", False),
            }
        else:
            error_msg = result.get("error", "Unknown error")
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": error_msg,
            }
    except Exception as e:
        logger.error(f"Exception setting budget: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/create-campaign", summary="Create a new Google Ads campaign",
             description="Create a new search campaign via Google Ads API")
def create_campaign(req: CreateCampaignRequest, db: Session = Depends(get_db)):
    try:
        config = {
            "campaign_name": req.campaign_name,
            "daily_budget": req.daily_budget,
            "target_roas": req.target_roas,
        }
        result = service.create_campaign(config)
        if result.get("success"):
            _log_activity(db, "GOOGLE_CAMPAIGN_CREATED", result.get("external_id", ""),
                         f"Campaign '{req.campaign_name}' created (budget: ${req.daily_budget}/day)")
            return {
                "status": "created",
                "external_id": result.get("external_id"),
                "campaign_name": req.campaign_name,
                "daily_budget": req.daily_budget,
                "simulated": result.get("simulated", False),
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Unknown error"),
            }
    except Exception as e:
        logger.error(f"Exception creating campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/performance", summary="Fetch campaign performance",
            description="Get performance data for a specific campaign or all campaigns")
def get_performance(
    campaign_id: str = Query(None, description="Specific campaign ID (omit for all)"),
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
):
    try:
        data = service.get_performance(external_id=campaign_id, days=days)
        return {
            "status": "ok",
            "campaign_id": campaign_id,
            "days": days,
            "count": len(data),
            "performance": data,
        }
    except Exception as e:
        logger.error(f"Failed to fetch performance: {e}")
        return {"status": "error", "message": str(e)}
