"""
Dashboard API router - Status, metrics, and activity
"""

import os
import logging
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, CampaignModel, ActivityLogModel, ProductModel, MetaTokenModel

logger = logging.getLogger("AutoSEM.Dashboard")
router = APIRouter()


def _get_meta_token(db: Session) -> str:
    """Get Meta access token from DB or environment."""
    token_record = db.query(MetaTokenModel).first()
    if token_record and token_record.access_token:
        return token_record.access_token
    return os.environ.get("META_ACCESS_TOKEN", "")


@router.get("/status", summary="Get Dashboard Status",
            description="Get current system status and metrics")
def get_dashboard_status(db: Session = Depends(get_db)):
    active = db.query(CampaignModel).filter(CampaignModel.status == "active").count()
    today_spend = db.query(func.sum(CampaignModel.spend)).scalar() or 0
    today_revenue = db.query(func.sum(CampaignModel.revenue)).scalar() or 0
    today_roas = today_revenue / today_spend if today_spend > 0 else 0

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

    logger.warning(f"Emergency pause: {count} campaigns paused")
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

    logger.info(f"Resumed {count} campaigns")
    return {"status": "resumed", "campaigns_resumed": count}


@router.get("/dashboard", summary="Get Dashboard Page",
            description="Serve the dashboard HTML page")
def get_dashboard_page():
    # Try multiple template locations
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "design_doc.html"),
        os.path.join(os.path.dirname(__file__), "..", "..", "templates", "dashboard.html"),
    ]
    for template_path in possible_paths:
        if os.path.exists(template_path):
            with open(template_path) as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard</h1><p>No template found</p>")


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
    access_token = _get_meta_token(db)
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")

    if not access_token or not ad_account_id:
        return {"platform": "meta", "error": "Meta Ads not configured"}

    try:
        # Fetch all campaigns with insights
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

        resp = requests.get(
            f"https://graph.facebook.com/v19.0/act_{ad_account_id}/campaigns",
            params={
                "fields": "id,name,status,insights.time_range({{\"since\":\"{start}\",\"until\":\"{end}\"}}){{spend,impressions,clicks,reach,ctr,cpc}}".format(
                    start=start_date, end=end_date
                ),
                "access_token": access_token,
                "limit": 100,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        campaigns = []
        total_spend = 0
        total_impressions = 0
        total_clicks = 0
        total_reach = 0

        for campaign in data:
            insights = campaign.get("insights", {}).get("data", [{}])
            insight = insights[0] if insights else {}

            spend = float(insight.get("spend", 0))
            impressions = int(insight.get("impressions", 0))
            clicks = int(insight.get("clicks", 0))
            reach = int(insight.get("reach", 0))
            ctr = float(insight.get("ctr", 0))
            cpc = float(insight.get("cpc", 0))

            if spend > 0 or impressions > 0:
                campaigns.append({
                    "id": campaign["id"],
                    "name": campaign.get("name", ""),
                    "status": campaign.get("status", "UNKNOWN"),
                    "spend": round(spend, 2),
                    "impressions": impressions,
                    "clicks": clicks,
                    "reach": reach,
                    "ctr": round(ctr, 2),
                    "cpc": round(cpc, 2),
                })
                total_spend += spend
                total_impressions += impressions
                total_clicks += clicks
                total_reach += reach

        avg_ctr = round((total_clicks / total_impressions * 100) if total_impressions > 0 else 0, 2)
        avg_cpc = round((total_spend / total_clicks) if total_clicks > 0 else 0, 2)

        return {
            "platform": "meta",
            "last_synced": datetime.utcnow().isoformat(),
            "summary": {
                "total_campaigns": len(campaigns),
                "total_spend": round(total_spend, 2),
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "total_reach": total_reach,
                "avg_ctr": avg_ctr,
                "avg_cpc": avg_cpc,
            },
            "campaigns": campaigns,
        }

    except Exception as e:
        logger.error(f"Failed to fetch Meta performance: {e}")
        return {"platform": "meta", "error": str(e)}


@router.post("/sync-meta", summary="Sync Meta Performance",
             description="Sync Meta Ads performance data and update database")
def sync_meta_performance(db: Session = Depends(get_db)):
    # Reuse the meta-performance endpoint logic and update local campaign records
    perf = get_meta_performance(db)
    if "error" in perf:
        return {"status": "error", "message": perf["error"]}

    synced = 0
    for meta_campaign in perf.get("campaigns", []):
        local = db.query(CampaignModel).filter(
            CampaignModel.platform_campaign_id == meta_campaign["id"]
        ).first()
        if local:
            local.spend = meta_campaign["spend"]
            local.status = meta_campaign["status"].lower()
            synced += 1
    db.commit()

    return {"status": "synced", "campaigns_synced": synced, "summary": perf.get("summary")}


@router.post("/fix-data", summary="Fix Database Data",
             description="Fix campaign data - delete unwanted campaigns and fix budgets")
def fix_database_data(db: Session = Depends(get_db)):
    fixed = 0
    campaigns = db.query(CampaignModel).filter(CampaignModel.daily_budget == None).all()
    for c in campaigns:
        c.daily_budget = 1.03
        fixed += 1
    db.commit()

    return {"status": "fixed", "campaigns_fixed": fixed}
