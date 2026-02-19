"""
Health Check Router — Deep system status
GET /api/v1/health/deep returns structured health report.
"""

import os
import time
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import (
    get_db, engine, CampaignModel, MetaTokenModel,
    TikTokTokenModel, ActivityLogModel,
)

logger = logging.getLogger("AutoSEM.Health")
router = APIRouter()


@router.get("/deep", summary="Deep health check",
            description="Structured system status: DB, tokens, scheduler, campaigns, spend/revenue")
def deep_health(db: Session = Depends(get_db)):
    report = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    issues = []

    # ─── Database Connectivity ───
    try:
        db.execute(text("SELECT 1"))
        report["checks"]["database"] = {"status": "ok", "engine": str(engine.url).split("@")[-1] if "@" in str(engine.url) else "sqlite"}
    except Exception as e:
        report["checks"]["database"] = {"status": "error", "message": str(e)}
        issues.append("database")

    # ─── Meta Token ───
    try:
        meta_token = db.query(MetaTokenModel).first()
        if meta_token and meta_token.access_token:
            expires_at = meta_token.expires_at
            days_remaining = None
            if expires_at:
                delta = (expires_at - datetime.now(timezone.utc)).days if expires_at.tzinfo else (expires_at - datetime.utcnow()).days
                days_remaining = max(0, delta)

            token_status = "ok"
            if days_remaining is not None and days_remaining < 3:
                token_status = "expiring_soon"
                issues.append("meta_token_expiring")

            report["checks"]["meta_token"] = {
                "status": token_status,
                "present": True,
                "days_remaining": days_remaining,
                "token_prefix": meta_token.access_token[:12] + "...",
            }
        else:
            env_token = os.environ.get("META_ACCESS_TOKEN", "")
            report["checks"]["meta_token"] = {
                "status": "ok" if env_token else "not_configured",
                "present": bool(env_token),
                "source": "env" if env_token else None,
            }
            if not env_token:
                issues.append("meta_token_missing")
    except Exception as e:
        report["checks"]["meta_token"] = {"status": "error", "message": str(e)}

    # ─── TikTok Token ───
    try:
        tiktok_token = db.query(TikTokTokenModel).first()
        env_tiktok = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
        has_token = bool((tiktok_token and tiktok_token.access_token) or env_tiktok)
        report["checks"]["tiktok_token"] = {
            "status": "ok" if has_token else "not_configured",
            "present": has_token,
        }
    except Exception as e:
        report["checks"]["tiktok_token"] = {"status": "error", "message": str(e)}

    # ─── Shopify Token ───
    try:
        from app.routers.shopify import _token_cache
        shopify_token = _token_cache.get("access_token", "")
        expires_at = _token_cache.get("expires_at", 0)
        ttl_seconds = max(0, int(expires_at - time.time()))
        report["checks"]["shopify_token"] = {
            "status": "ok" if shopify_token and ttl_seconds > 0 else "expired",
            "present": bool(shopify_token),
            "ttl_seconds": ttl_seconds,
            "ttl_hours": round(ttl_seconds / 3600, 1),
        }
        if not shopify_token or ttl_seconds <= 0:
            issues.append("shopify_token_expired")
    except Exception as e:
        report["checks"]["shopify_token"] = {"status": "error", "message": str(e)}

    # ─── Klaviyo ───
    klaviyo_key = os.environ.get("KLAVIYO_API_KEY", "")
    report["checks"]["klaviyo"] = {
        "status": "ok" if klaviyo_key else "not_configured",
        "configured": bool(klaviyo_key),
    }

    # ─── Scheduler Heartbeat ───
    try:
        from scheduler import scheduler as bg_scheduler
        report["checks"]["scheduler"] = {
            "status": "running" if bg_scheduler.running else "stopped",
            "running": bg_scheduler.running,
            "jobs": len(bg_scheduler.get_jobs()) if bg_scheduler.running else 0,
        }
        if not bg_scheduler.running:
            issues.append("scheduler_stopped")
    except Exception as e:
        report["checks"]["scheduler"] = {"status": "not_loaded", "message": str(e)}
        issues.append("scheduler_not_loaded")

    # ─── Last Optimization ───
    try:
        last_opt = db.query(ActivityLogModel).filter(
            ActivityLogModel.action == "AUTOMATION_CYCLE",
        ).order_by(ActivityLogModel.timestamp.desc()).first()

        if last_opt:
            report["checks"]["last_optimization"] = {
                "status": "ok",
                "timestamp": last_opt.timestamp.isoformat() if last_opt.timestamp else None,
            }
        else:
            report["checks"]["last_optimization"] = {
                "status": "never_run",
                "timestamp": None,
            }
    except Exception as e:
        report["checks"]["last_optimization"] = {"status": "error", "message": str(e)}

    # ─── Campaign Counts ───
    try:
        total = db.query(func.count(CampaignModel.id)).scalar() or 0
        active = db.query(func.count(CampaignModel.id)).filter(
            CampaignModel.status.in_(["active", "ACTIVE", "live"])
        ).scalar() or 0
        paused = db.query(func.count(CampaignModel.id)).filter(
            CampaignModel.status.in_(["paused", "PAUSED"])
        ).scalar() or 0
        draft = db.query(func.count(CampaignModel.id)).filter(
            CampaignModel.status == "draft"
        ).scalar() or 0

        report["checks"]["campaigns"] = {
            "status": "ok",
            "total": total,
            "active": active,
            "paused": paused,
            "draft": draft,
        }
    except Exception as e:
        report["checks"]["campaigns"] = {"status": "error", "message": str(e)}

    # ─── Spend / Revenue ───
    try:
        total_spend = db.query(func.sum(CampaignModel.total_spend)).scalar() or 0
        total_revenue = db.query(func.sum(CampaignModel.total_revenue)).scalar() or 0
        overall_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

        report["checks"]["financials"] = {
            "status": "ok",
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "overall_roas": overall_roas,
            "net": round(total_revenue - total_spend, 2),
        }
    except Exception as e:
        report["checks"]["financials"] = {"status": "error", "message": str(e)}

    # ─── Overall Status ───
    if issues:
        report["status"] = "degraded"
        report["issues"] = issues

    return report
