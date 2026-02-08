"""
Automation API router - Core orchestration engine
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

_automation_state = {
    "is_running": True,
    "last_optimization": None,
    "daily_spend": 0.0,
    "daily_revenue": 0.0,
    "roas": 0,
}


@router.get("/status", summary="Get Automation Status")
def get_automation_status() -> dict:
    return _automation_state


@router.post("/start", summary="Start Automation")
def start_automation() -> dict:
    _automation_state["is_running"] = True
    return {"status": "started", "is_running": True}


@router.post("/stop", summary="Stop Automation")
def stop_automation() -> dict:
    _automation_state["is_running"] = False
    return {"status": "stopped", "is_running": False}


@router.post("/run-cycle", summary="Run Automation Cycle")
def run_automation_cycle(db: Session = Depends(get_db)) -> dict:
    if not _automation_state["is_running"]:
        return {"status": "error", "message": "Automation is paused"}

    results = {"cycle_start": datetime.utcnow().isoformat(), "steps": []}

    try:
        generator = CampaignGenerator()
        new_campaigns = generator.create_for_uncovered_products(db)
        results["steps"].append({"step": "create_campaigns", "created": new_campaigns})
    except Exception as e:
        results["steps"].append({"step": "create_campaigns", "error": str(e)})

    try:
        optimizer = CampaignOptimizer()
        optimizations = optimizer.optimize_all(db)
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

    log = ActivityLogModel(action="AUTOMATION_CYCLE", details=json.dumps(results, default=str))
    db.add(log)
    db.commit()
    return results


@router.post("/create-campaigns", summary="Create Campaigns")
def create_campaigns(db: Session = Depends(get_db)) -> dict:
    generator = CampaignGenerator()
    try:
        created = generator.create_for_uncovered_products(db)
        return {"status": "success", "campaigns_created": created}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/optimize", summary="Run Optimization")
def run_optimization(db: Session = Depends(get_db)) -> dict:
    optimizer = CampaignOptimizer()
    try:
        results = optimizer.optimize_all(db)
        return {"status": "success", "optimizations": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/push-live", summary="Push Campaigns Live")
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
    log = ActivityLogModel(action="PUSH_LIVE", details=json.dumps(pushed))
    db.add(log)
    db.commit()
    return pushed


@router.post("/sync-performance", summary="Sync Performance")
def sync_performance(db: Session = Depends(get_db)) -> dict:
    google_ads = GoogleAdsService()
    try:
        result = google_ads.sync_performance(db)
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/update-meta-token", summary="Update Meta Token")
def update_meta_token(token_data: TokenUpdate, db: Session = Depends(get_db)) -> dict:
    meta = MetaAdsService()
    try:
        result = meta.exchange_token(token_data.access_token, db)
        return {"status": "success", **result}
    except Exception as e:
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
        return {"action": "EMERGENCY_PAUSE", "net_loss": net_loss}

    if total_spend >= daily_limit:
        return {"action": "DAILY_LIMIT_REACHED", "spend": total_spend}

    return {"action": "OK", "spend": total_spend, "limit": daily_limit}
