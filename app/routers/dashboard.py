"""
Dashboard API router - Status, metrics, and activity
"""

import os
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, CampaignModel, ActivityLogModel, ProductModel

logger = logging.getLogger("AutoSEM.Dashboard")
router = APIRouter()


@router.get("/status", summary="Get Dashboard Status",
            description="Get current system status and metrics")
def get_dashboard_status(db: Session = Depends(get_db)):
    active = db.query(CampaignModel).filter(CampaignModel.status == "active").count()
    today_spend = db.query(func.sum(CampaignModel.spend)).scalar() or 0
    today_revenue = db.query(func.sum(CampaignModel.revenue)).scalar() or 0
    today_roas = today_revenue / today_spend if today_spend > 0 else 0

    # Get actions today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    actions_today = db.query(ActivityLogModel).filter(
        ActivityLogModel.timestamp >= today_start
    ).count()

    return {
        "status": "operational",
        "last_optimization": "1 day ago",
        "actions_today": actions_today,
        "spend_today": round(today_spend, 2),
        "revenue_today": round(today_revenue, 2),
        "roas_today": round(today_roas, 2),
        "orders_today": 0,
        "active_campaigns": active,
    }


@router.post("/pause-all", summary="Pause All Campaigns",
             description="Emergency pause all campaigns")
def pause_all_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(CampaignModel).filter(CampaignModel.status == "active").all()
    count = 0
    for c in campaigns:
        c.status = "PAUSED"
        count += 1
    db.commit()

    log = ActivityLogModel(action="EMERGENCY_PAUSE", details=f"Paused {count} campaigns")
    db.add(log)
    db.commit()

    logger.warning(f"\u26a0\ufe0f Emergency pause: {count} campaigns paused")
    return {"status": "paused", "campaigns_paused": count}


@router.post("/resume-all", summary="Resume All Campaigns",
             description="Resume all paused campaigns")
def resume_all_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(CampaignModel).filter(CampaignModel.status == "PAUSED").all()
    count = 0
    for c in campaigns:
        c.status = "active"
        count += 1
    db.commit()

    log = ActivityLogModel(action="RESUME_ALL", details=f"Resumed {count} campaigns")
    db.add(log)
    db.commit()

    logger.info(f"\u2705 Resumed {count} campaigns")
    return {"status": "resumed", "campaigns_resumed": count}


@router.get("/dashboard", summary="Get Dashboard Page",
            description="Serve the dashboard HTML page")
def get_dashboard_page():
    template_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard</h1>")


@router.get("/metrics/daily", summary="Get Daily Metrics",
            description="Get detailed daily metrics")
def get_daily_metrics(db: Session = Depends(get_db)):
    total_spend = db.query(func.sum(CampaignModel.spend)).scalar() or 0
    total_revenue = db.query(func.sum(CampaignModel.revenue)).scalar() or 0
    total_conversions = db.query(func.sum(CampaignModel.conversions)).scalar() or 0
    roas = total_revenue / total_spend if total_spend > 0 else 0

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "spend": round(total_spend, 2),
        "revenue": round(total_revenue, 2),
        "conversions": total_conversions,
        "roas": round(roas, 2),
        "cpa": round(total_spend / total_conversions, 2) if total_conversions > 0 else 0,
    }


@router.get("/metrics/weekly", summary="Get Weekly Metrics",
            description="Get weekly metrics for reporting")
def get_weekly_metrics(db: Session = Depends(get_db)):
    total_spend = db.query(func.sum(CampaignModel.total_spend)).scalar() or 0
    total_revenue = db.query(func.sum(CampaignModel.total_revenue)).scalar() or 0
    total_conversions = db.query(func.sum(CampaignModel.conversions)).scalar() or 0

    return {
        "period": "last_7_days",
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
        "total_conversions": total_conversions,
        "avg_roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0,
    }


@router.get("/campaigns/performance", summary="Get Campaign Performance",
            description="Get performance data for all campaigns")
def get_campaign_performance(db: Session = Depends(get_db)):
    campaigns = db.query(CampaignModel).filter(CampaignModel.status == "active").all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "platform": c.platform,
            "spend": c.spend,
            "revenue": c.revenue,
            "roas": c.roas,
            "conversions": c.conversions,
            "status": c.status,
        }
        for c in campaigns
    ]


@router.get("/activity", summary="Get Recent Activity",
            description="Get recent optimization activity from logs")
def get_recent_activity(limit: int = 10, db: Session = Depends(get_db)):
    logs = db.query(ActivityLogModel).order_by(
        ActivityLogModel.timestamp.desc()
    ).limit(limit).all()

    return [
        {
            "id": log.id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


@router.post("/log-activity", summary="Log Activity",
             description="Log an optimization activity")
def log_activity(
    action: str,
    entity_type: str = None,
    entity_id: str = None,
    details: str = None,
    db: Session = Depends(get_db),
):
    log = ActivityLogModel(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(log)
    db.commit()
    return {"status": "logged", "id": log.id}


@router.get("/meta-performance", summary="Get Meta Performance",
            description="Fetch live performance data directly from Meta Ads API")
def get_meta_performance(db: Session = Depends(get_db)):
    from app.services.meta_ads import MetaAdsService
    meta = MetaAdsService()
    try:
        return meta.get_performance(db)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/sync-meta", summary="Sync Meta Performance",
             description="Sync Meta Ads performance data and update database")
def sync_meta_performance(db: Session = Depends(get_db)):
    from app.services.meta_ads import MetaAdsService
    meta = MetaAdsService()
    try:
        return meta.sync_performance(db)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/fix-data", summary="Fix Database Data",
             description="Fix campaign data - delete unwanted campaigns and fix budgets")
def fix_database_data(db: Session = Depends(get_db)):
    # Fix any campaigns with null budgets
    fixed = 0
    campaigns = db.query(CampaignModel).filter(CampaignModel.daily_budget == None).all()
    for c in campaigns:
        c.daily_budget = 1.03  # Default budget
        fixed += 1
    db.commit()

    return {"status": "fixed", "campaigns_fixed": fixed}
