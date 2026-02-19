"""Automation API router - Core orchestration engine
Handles campaign creation, optimization, and lifecycle management
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, CampaignModel, ProductModel, ActivityLogModel, MetaTokenModel
from app.schemas import TokenUpdate
from app.services.campaign_generator import CampaignGenerator
from app.services.optimizer import CampaignOptimizer
from app.services.google_ads import GoogleAdsService
from app.services.meta_ads import MetaAdsService

logger = logging.getLogger("AutoSEM.Automation")
router = APIRouter()

# In-memory automation state
_automation_state = {
    "is_running": True,
    "last_optimization": None,
    "daily_spend": 0.0,
    "daily_revenue": 0.0,
    "roas": 0,
}


@router.get("/status", summary="Get Automation Status",
            description="Get current automation engine status including scheduler heartbeats")
def get_automation_status(db: Session = Depends(get_db)) -> dict:
    from app.database import SettingsModel

    # Read heartbeat timestamps from DB
    last_opt = db.query(SettingsModel).filter(SettingsModel.key == "last_optimization").first()
    last_sync = db.query(SettingsModel).filter(SettingsModel.key == "last_sync_performance").first()

    return {
        **_automation_state,
        "last_optimization": last_opt.value if last_opt else _automation_state.get("last_optimization"),
        "last_sync_performance": last_sync.value if last_sync else None,
    }


@router.post("/start", summary="Start Automation",
             description="Start the automation engine")
def start_automation() -> dict:
    _automation_state["is_running"] = True
    logger.info("\ud83d\udfe2 Automation engine started")
    return {"status": "started", "is_running": True}


@router.post("/stop", summary="Stop Automation",
             description="Stop the automation engine")
def stop_automation() -> dict:
    _automation_state["is_running"] = False
    logger.info("\ud83d\udd34 Automation engine stopped")
    return {"status": "stopped", "is_running": False}


@router.post("/run-cycle", summary="Run Automation Cycle",
             description="Manually trigger a full automation cycle")
def run_automation_cycle(db: Session = Depends(get_db)) -> dict:
    if not _automation_state["is_running"]:
        return {"status": "error", "message": "Automation is paused"}

    results = {
        "cycle_start": datetime.utcnow().isoformat(),
        "steps": [],
    }

    # Bug 1 fix: pass db to constructors, call methods without db arg
    try:
        generator = CampaignGenerator(db)
        new_campaigns = generator.generate_campaigns()
        results["steps"].append({"step": "create_campaigns", "created": len(new_campaigns)})
    except Exception as e:
        results["steps"].append({"step": "create_campaigns", "error": str(e)})

    try:
        optimizer = CampaignOptimizer(db)
        optimizations = optimizer.optimize_all()
        results["steps"].append({"step": "optimize", "actions": optimizations})
    except Exception as e:
        results["steps"].append({"step": "optimize", "error": str(e)})

    try:
        safety = _check_safety_limits(db)
        results["steps"].append({"step": "safety_check", **safety})
    except Exception as e:
        results["steps"].append({"step": "safety_check", "error": str(e)})

    _automation_state["last_optimization"] = datetime.utcnow().isoformat()
    results["cycle_end"] = datetime.utcnow().isoformat()

    log = ActivityLogModel(
        action="AUTOMATION_CYCLE",
        details=json.dumps(results, default=str),
    )
    db.add(log)
    db.commit()

    return results


@router.post("/create-campaigns", summary="Create Campaigns",
             description="Create AI-powered campaigns for products without campaigns")
def create_campaigns(db: Session = Depends(get_db)) -> dict:
    generator = CampaignGenerator(db)
    try:
        created = generator.generate_campaigns()
        return {"status": "success", "campaigns_created": len(created), "campaigns": created}
    except Exception as e:
        logger.error(f"Campaign creation failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/optimize", summary="Run Optimization",
             description="Run optimization on all active campaigns")
def run_optimization(db: Session = Depends(get_db)) -> dict:
    optimizer = CampaignOptimizer(db)
    try:
        results = optimizer.optimize_all()
        return {"status": "success", "optimizations": results}
    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/push-live", summary="Push Campaigns Live",
             description="Push all pending campaigns to Google Ads and make them live")
def push_campaigns_live(db: Session = Depends(get_db)) -> dict:
    google_ads = GoogleAdsService()
    meta_ads = MetaAdsService()
    pushed = {"google_ads": 0, "meta": 0, "errors": []}

    google_campaigns = db.query(CampaignModel).filter(
        CampaignModel.platform == "google_ads",
        CampaignModel.platform_campaign_id == None,
        CampaignModel.status == "active",
    ).all()

    for campaign in google_campaigns:
        try:
            result = google_ads.create_campaign(campaign, db)
            if result:
                campaign.platform_campaign_id = result
                pushed["google_ads"] += 1
        except Exception as e:
            pushed["errors"].append(f"Google: {campaign.name}: {str(e)}")

    meta_campaigns = db.query(CampaignModel).filter(
        CampaignModel.platform == "meta",
        CampaignModel.platform_campaign_id == None,
        CampaignModel.status == "active",
    ).all()

    for campaign in meta_campaigns:
        try:
            result = meta_ads.create_campaign(campaign, db)
            if result:
                campaign.platform_campaign_id = result
                pushed["meta"] += 1
        except Exception as e:
            pushed["errors"].append(f"Meta: {campaign.name}: {str(e)}")

    db.commit()

    log = ActivityLogModel(
        action="PUSH_LIVE",
        details=json.dumps(pushed),
    )
    db.add(log)
    db.commit()

    logger.info(f"Pushed live: {pushed['google_ads']} Google, {pushed['meta']} Meta")
    return pushed


@router.post("/sync-performance", summary="Sync Performance",
             description="Sync performance data from Meta and TikTok ad platforms")
def sync_performance(db: Session = Depends(get_db)) -> dict:
    """Bug 2 fix: Use PerformanceSyncService instead of non-existent google_ads method."""
    try:
        from app.services.performance_sync import PerformanceSyncService
        sync_service = PerformanceSyncService(db)
        result = sync_service.sync_all()
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Performance sync failed: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/update-meta-token", summary="Update Meta Token",
             description="Exchange short-lived Meta token for long-lived token")
def update_meta_token(token_data: TokenUpdate, db: Session = Depends(get_db)) -> dict:
    meta = MetaAdsService()
    try:
        result = meta.exchange_token(token_data.access_token, db)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Meta token update failed: {e}")
        return {"status": "error", "message": str(e)}


def _check_safety_limits(db: Session) -> dict:
    from app.routers.settings import _get_setting, DEFAULT_SETTINGS

    daily_limit = float(_get_setting(db, "daily_spend_limit", DEFAULT_SETTINGS["daily_spend_limit"]))
    emergency_limit = float(_get_setting(db, "emergency_pause_loss", DEFAULT_SETTINGS["emergency_pause_loss"]))

    total_spend = db.query(func.sum(CampaignModel.spend)).scalar() or 0
    total_revenue = db.query(func.sum(CampaignModel.revenue)).scalar() or 0
    net_loss = total_spend - total_revenue

    if net_loss >= emergency_limit:
        campaigns = db.query(CampaignModel).filter(CampaignModel.status == "active").all()
        for c in campaigns:
            c.status = "PAUSED"
        db.commit()
        logger.critical(f"\ud83d\udea8 EMERGENCY PAUSE: Net loss ${net_loss:.2f} exceeds ${emergency_limit}")
        return {"action": "EMERGENCY_PAUSE", "net_loss": net_loss}

    if total_spend >= daily_limit:
        logger.warning(f"\u26a0\ufe0f Daily spend limit reached: ${total_spend:.2f} >= ${daily_limit}")
        return {"action": "DAILY_LIMIT_REACHED", "spend": total_spend}

    return {"action": "OK", "spend": total_spend, "limit": daily_limit}
