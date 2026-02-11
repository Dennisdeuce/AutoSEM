"""
Dashboard API router - Status, metrics, and activity
Aggregates live data from Meta + TikTok APIs for summary metrics
v1.1.0 - Aggregate all platforms in top summary boxes
"""

import os
import json
import logging
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, CampaignModel, ActivityLogModel, MetaTokenModel, TikTokTokenModel

logger = logging.getLogger("AutoSEM.Dashboard")
router = APIRouter()

TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def _get_meta_token(db: Session) -> str:
    try:
        token_record = db.query(MetaTokenModel).first()
        if token_record and token_record.access_token:
            return token_record.access_token
    except Exception:
        pass
    return os.environ.get("META_ACCESS_TOKEN", "")


def _get_tiktok_token(db: Session) -> dict:
    try:
        token_record = db.query(TikTokTokenModel).first()
        if token_record and token_record.access_token:
            return {"access_token": token_record.access_token, "advertiser_id": token_record.advertiser_id}
    except Exception:
        pass
    return {"access_token": os.environ.get("TIKTOK_ACCESS_TOKEN", ""),
            "advertiser_id": os.environ.get("TIKTOK_ADVERTISER_ID", "")}


def _fetch_meta_7d(db: Session) -> dict:
    """Fetch last 7 days of Meta Ads data."""
    access_token = _get_meta_token(db)
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
    if not access_token or not ad_account_id:
        return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}
    try:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/act_{ad_account_id}/insights",
            params={
                "time_range": '{"since":"' + start_date + '","until":"' + end_date + '"}',
                "fields": "spend,impressions,clicks",
                "access_token": access_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return {
                "spend": float(data[0].get("spend", 0)),
                "impressions": int(data[0].get("impressions", 0)),
                "clicks": int(data[0].get("clicks", 0)),
                "connected": True,
            }
        return {"spend": 0, "impressions": 0, "clicks": 0, "connected": True}
    except Exception as e:
        logger.warning(f"Failed to fetch Meta spend: {e}")
    return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}


def _fetch_tiktok_7d(db: Session) -> dict:
    """Fetch last 7 days of TikTok Ads data."""
    creds = _get_tiktok_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}
    try:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        headers = {"Access-Token": creds["access_token"], "Content-Type": "application/json"}
        resp = requests.get(
            f"{TIKTOK_API_BASE}/report/integrated/get/",
            headers=headers,
            params={
                "advertiser_id": creds["advertiser_id"],
                "report_type": "BASIC",
                "dimensions": json.dumps(["campaign_id"]),
                "data_level": "AUCTION_CAMPAIGN",
                "start_date": start_date,
                "end_date": end_date,
                "metrics": json.dumps(["spend", "impressions", "clicks"]),
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0:
            data = result.get("data", {})
            if isinstance(data, list):
                data = data[0] if data else {}
            rows = data.get("list", [])
            total_spend = sum(float(r.get("metrics", {}).get("spend", 0)) for r in rows)
            total_imp = sum(int(r.get("metrics", {}).get("impressions", 0)) for r in rows)
            total_clicks = sum(int(r.get("metrics", {}).get("clicks", 0)) for r in rows)
            return {"spend": total_spend, "impressions": total_imp, "clicks": total_clicks, "connected": True}
        return {"spend": 0, "impressions": 0, "clicks": 0, "connected": True}
    except Exception as e:
        logger.warning(f"Failed to fetch TikTok spend: {e}")
    return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}


@router.get("/status", summary="Dashboard Status - Aggregated")
def get_dashboard_status(db: Session = Depends(get_db)):
    try:
        active = db.query(CampaignModel).filter(CampaignModel.status.in_(["active", "ACTIVE"])).count()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        actions_today = db.query(ActivityLogModel).filter(
            ActivityLogModel.timestamp >= today_start
        ).count()

        # Aggregate from all live platform APIs
        meta = _fetch_meta_7d(db)
        tiktok = _fetch_tiktok_7d(db)

        total_spend = meta["spend"] + tiktok["spend"]
        total_impressions = meta["impressions"] + tiktok["impressions"]
        total_clicks = meta["clicks"] + tiktok["clicks"]

        platforms_connected = []
        if meta["connected"]:
            platforms_connected.append("meta")
        if tiktok["connected"]:
            platforms_connected.append("tiktok")

        return {
            "status": "operational",
            "last_optimization": "running",
            "actions_today": actions_today,
            "spend_7d": round(total_spend, 2),
            "impressions_7d": total_impressions,
            "clicks_7d": total_clicks,
            "ctr_7d": round((total_clicks / total_impressions * 100) if total_impressions > 0 else 0, 2),
            "active_campaigns": active,
            "platforms_connected": platforms_connected,
            "meta_spend": round(meta["spend"], 2),
            "tiktok_spend": round(tiktok["spend"], 2),
        }
    except Exception as e:
        logger.error(f"Dashboard status error: {e}")
        return JSONResponse(status_code=200, content={
            "status": "degraded", "last_optimization": "unknown",
            "actions_today": 0, "spend_7d": 0, "impressions_7d": 0,
            "clicks_7d": 0, "ctr_7d": 0, "active_campaigns": 0,
            "platforms_connected": [], "error": str(e),
        })


@router.post("/pause-all", summary="Emergency Pause All")
def pause_all_campaigns(db: Session = Depends(get_db)):
    try:
        campaigns = db.query(CampaignModel).filter(CampaignModel.status.in_(["active", "ACTIVE"])).all()
        count = 0
        for c in campaigns:
            c.status = "PAUSED"
            count += 1
        db.commit()
        db.add(ActivityLogModel(action="EMERGENCY_PAUSE", details=f"Paused {count} campaigns"))
        db.commit()
        return {"status": "paused", "campaigns_paused": count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/resume-all", summary="Resume All")
def resume_all_campaigns(db: Session = Depends(get_db)):
    try:
        campaigns = db.query(CampaignModel).filter(CampaignModel.status == "PAUSED").all()
        count = 0
        for c in campaigns:
            c.status = "active"
            count += 1
        db.commit()
        db.add(ActivityLogModel(action="RESUME_ALL", details=f"Resumed {count} campaigns"))
        db.commit()
        return {"status": "resumed", "campaigns_resumed": count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/activity", summary="Recent Activity")
def get_recent_activity(limit: int = 10, db: Session = Depends(get_db)):
    try:
        logs = db.query(ActivityLogModel).order_by(
            ActivityLogModel.timestamp.desc()
        ).limit(limit).all()
        return [
            {
                "id": log.id, "action": log.action, "entity_type": log.entity_type,
                "entity_id": log.entity_id, "details": log.details,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ]
    except Exception as e:
        logger.error(f"Activity log error: {e}")
        return []


@router.post("/log-activity", summary="Log Activity")
def log_activity(action: str, entity_type: str = None, entity_id: str = None,
                details: str = None, db: Session = Depends(get_db)):
    try:
        log = ActivityLogModel(action=action, entity_type=entity_type,
                               entity_id=entity_id, details=details)
        db.add(log)
        db.commit()
        return {"status": "logged", "id": log.id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/meta-performance", summary="Meta Performance (7d)")
def get_meta_performance(db: Session = Depends(get_db)):
    access_token = _get_meta_token(db)
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
    if not access_token or not ad_account_id:
        return {"platform": "meta", "error": "Meta Ads not configured"}
    try:
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
        total_spend = total_impressions = total_clicks = total_reach = 0
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
                    "id": campaign["id"], "name": campaign.get("name", ""),
                    "status": campaign.get("status", "UNKNOWN"),
                    "spend": round(spend, 2), "impressions": impressions,
                    "clicks": clicks, "reach": reach,
                    "ctr": round(ctr, 2), "cpc": round(cpc, 2),
                })
                total_spend += spend
                total_impressions += impressions
                total_clicks += clicks
                total_reach += reach
        avg_ctr = round((total_clicks / total_impressions * 100) if total_impressions > 0 else 0, 2)
        avg_cpc = round((total_spend / total_clicks) if total_clicks > 0 else 0, 2)
        return {
            "platform": "meta", "last_synced": datetime.utcnow().isoformat(),
            "summary": {
                "total_campaigns": len(campaigns), "total_spend": round(total_spend, 2),
                "total_impressions": total_impressions, "total_clicks": total_clicks,
                "total_reach": total_reach, "avg_ctr": avg_ctr, "avg_cpc": avg_cpc,
            },
            "campaigns": campaigns,
        }
    except Exception as e:
        logger.error(f"Failed to fetch Meta performance: {e}")
        return {"platform": "meta", "error": str(e)}


@router.post("/sync-meta", summary="Sync Meta Performance")
def sync_meta_performance(db: Session = Depends(get_db)):
    perf = get_meta_performance(db)
    if "error" in perf:
        return {"status": "error", "message": perf["error"]}
    synced = 0
    for mc in perf.get("campaigns", []):
        local = db.query(CampaignModel).filter(CampaignModel.platform_campaign_id == mc["id"]).first()
        if local:
            local.spend = mc["spend"]
            local.status = mc["status"].lower()
            synced += 1
    db.commit()
    return {"status": "synced", "campaigns_synced": synced, "summary": perf.get("summary")}


@router.post("/fix-data", summary="Fix Database Data")
def fix_database_data(db: Session = Depends(get_db)):
    fixed = 0
    campaigns = db.query(CampaignModel).filter(CampaignModel.daily_budget == None).all()
    for c in campaigns:
        c.daily_budget = 1.03
        fixed += 1
    db.commit()
    return {"status": "fixed", "campaigns_fixed": fixed}
