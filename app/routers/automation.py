"""Automation API router - Core orchestration engine
Handles campaign creation, optimization, and lifecycle management
"""

import os
import json
import logging
import asyncio
import time
import requests as http_requests
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, CampaignModel, ProductModel, ActivityLogModel, MetaTokenModel, SettingsModel
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
             description="Run optimization on all active campaigns. Generates recommendations when pre-revenue.")
def run_optimization(db: Session = Depends(get_db)) -> dict:
    optimizer = CampaignOptimizer(db)
    try:
        results = optimizer.optimize_all()

        # Pre-revenue recommendation engine
        recommendations = []
        total_conversions = db.query(func.sum(CampaignModel.conversions)).scalar() or 0
        total_spend = db.query(func.sum(CampaignModel.spend)).scalar() or 0
        total_revenue = db.query(func.sum(CampaignModel.revenue)).scalar() or 0

        if total_conversions == 0 and total_spend >= 50:
            # Generate structured recommendations
            active_campaigns = db.query(CampaignModel).filter(
                CampaignModel.status.in_(["active", "ACTIVE"])
            ).all()
            recs = []
            for c in active_campaigns:
                c_spend = c.spend or 0
                c_clicks = c.clicks or 0
                c_cpc = round(c_spend / c_clicks, 2) if c_clicks > 0 else 0
                c_ctr = round((c_clicks / c.impressions * 100) if c.impressions and c.impressions > 0 else 0, 2)

                if c_cpc > 1.00:
                    recs.append(f"Campaign '{c.name}': CPC ${c_cpc} too high — consider pausing or narrowing audience")
                if c_ctr < 1.0 and (c.impressions or 0) > 500:
                    recs.append(f"Campaign '{c.name}': CTR {c_ctr}% too low — refresh ad creative")
                if c_clicks > 50 and total_conversions == 0:
                    recs.append(f"Campaign '{c.name}': {c_clicks} clicks, 0 sales — check landing page and checkout flow")

            if not recs:
                recs.append(f"${total_spend:.0f} spent with 0 conversions — review landing page, pixel firing, and checkout UX")

            rec_text = "; ".join(recs)
            db.add(ActivityLogModel(
                action="OPTIMIZER_RECOMMENDATION",
                entity_type="optimizer",
                details=rec_text[:2000],
            ))
            db.commit()
            recommendations = recs

        # First revenue detection
        if total_revenue > 0:
            prev_rev_log = db.query(ActivityLogModel).filter(
                ActivityLogModel.action == "FIRST_REVENUE_DETECTED"
            ).first()
            if not prev_rev_log:
                db.add(ActivityLogModel(
                    action="FIRST_REVENUE_DETECTED",
                    entity_type="system",
                    details=f"First revenue detected! ${total_revenue:.2f} total. "
                            f"Recommend setting min_roas_threshold to 1.5 via PUT /api/v1/settings/",
                ))
                db.commit()
                recommendations.append(f"First revenue! ${total_revenue:.2f} — set min_roas_threshold to 1.5")

        return {
            "status": "success",
            "optimizations": results,
            "recommendations": recommendations if recommendations else None,
        }
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


@router.get("/activity-log", summary="View activity log",
            description="Get recent activity log entries, optionally filtered by action type")
def get_activity_log(
    limit: int = Query(50, ge=1, le=500),
    action: str = Query(None, description="Filter by action type (e.g. AUTO_OPTIMIZE, AUTOMATION_CYCLE)"),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(ActivityLogModel).order_by(ActivityLogModel.timestamp.desc())
    if action:
        query = query.filter(ActivityLogModel.action == action)
    logs = query.limit(limit).all()
    return {
        "status": "ok",
        "count": len(logs),
        "logs": [
            {
                "id": log.id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ],
    }


@router.get("/recommendations", summary="Get optimizer recommendations",
            description="Return last 10 optimizer recommendations from activity log")
def get_recommendations(db: Session = Depends(get_db)) -> dict:
    logs = db.query(ActivityLogModel).filter(
        ActivityLogModel.action.in_(["OPTIMIZER_RECOMMENDATION", "FIRST_REVENUE_DETECTED"])
    ).order_by(ActivityLogModel.timestamp.desc()).limit(10).all()
    return {
        "status": "ok",
        "count": len(logs),
        "recommendations": [
            {
                "id": log.id,
                "action": log.action,
                "details": log.details,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ],
    }


@router.post("/force-sync", summary="Force performance sync",
             description="Run performance sync immediately with verbose JSON output")
def force_sync(db: Session = Depends(get_db)) -> dict:
    """Trigger an immediate performance sync via scheduler force_sync_performance."""
    try:
        from scheduler import force_sync_performance
        result = force_sync_performance()
        return result
    except Exception as e:
        logger.error(f"Force sync failed: {e}")
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


# ─── Daily Check (cron-callable) ─────────────────────────────────

DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "autosem-deploy-2026")

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = "2024-01"

_shopify_token_cache: dict = {"token": "", "expires_at": 0.0}


def _shopify_token() -> str:
    """Get a valid Shopify token, refreshing via client_credentials if expired."""
    if time.time() < _shopify_token_cache["expires_at"] and _shopify_token_cache["token"]:
        return _shopify_token_cache["token"]
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        return ""
    try:
        resp = http_requests.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _shopify_token_cache["token"] = data.get("access_token", "")
        _shopify_token_cache["expires_at"] = time.time() + data.get("expires_in", 86399) - 300
        return _shopify_token_cache["token"]
    except Exception as e:
        logger.error(f"Shopify token refresh failed: {e}")
        return _shopify_token_cache.get("token", "")


def _shopify_get(endpoint: str) -> dict:
    """Make an authenticated GET to Shopify Admin API."""
    token = _shopify_token()
    if not token:
        return {"error": "no_shopify_token"}
    resp = http_requests.get(
        f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}",
        headers={"X-Shopify-Access-Token": token},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


@router.post("/daily-check",
             summary="Daily autonomous check (cron-callable)",
             description="Runs the full pipeline: sync performance, optimize, check for sales, "
                         "auto-exit awareness mode on first sale. Secured with X-Deploy-Key header. "
                         "Designed to be called by an external cron service every 6 hours.")
def daily_check(request: Request, db: Session = Depends(get_db)):
    """Full autonomous pipeline for external cron invocation."""
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    started = datetime.now(timezone.utc)
    report = {"steps": [], "timestamp": started.isoformat()}

    # ── Step 1: Sync performance data ────────────────────────────
    try:
        from app.services.performance_sync import PerformanceSyncService
        sync_service = PerformanceSyncService(db)
        sync_result = sync_service.sync_all()
        report["steps"].append({
            "step": "sync_performance",
            "status": "ok",
            "campaigns_synced": sync_result.get("meta", {}).get("campaigns_synced", 0),
            "details": sync_result,
        })
    except Exception as e:
        logger.error(f"daily-check sync failed: {e}", exc_info=True)
        report["steps"].append({"step": "sync_performance", "status": "error", "error": str(e)})

    # ── Step 2: Run optimizer ────────────────────────────────────
    try:
        optimizer = CampaignOptimizer(db)
        opt_result = optimizer.optimize_all()
        actions = opt_result.get("actions", [])
        report["steps"].append({
            "step": "optimize",
            "status": "ok",
            "campaigns_evaluated": opt_result.get("optimized", 0),
            "actions_taken": [a for a in actions if a.get("executed")],
            "actions_informational": [a for a in actions if not a.get("executed")],
        })
    except Exception as e:
        logger.error(f"daily-check optimize failed: {e}", exc_info=True)
        report["steps"].append({"step": "optimize", "status": "error", "error": str(e)})

    # ── Step 3: Check Shopify for orders ─────────────────────────
    shopify_step = {"step": "shopify_orders", "status": "skipped"}
    try:
        data = _shopify_get("customers.json?limit=50&fields=id,email,orders_count,total_spent")
        if "error" not in data:
            customers = data.get("customers", [])
            buyers = [c for c in customers if (c.get("orders_count") or 0) > 0]
            total_revenue = sum(float(c.get("total_spent", "0")) for c in buyers)
            shopify_step = {
                "step": "shopify_orders",
                "status": "ok",
                "total_customers": len(customers),
                "customers_with_orders": len(buyers),
                "total_revenue": round(total_revenue, 2),
            }
        else:
            shopify_step = {"step": "shopify_orders", "status": "skipped", "reason": data["error"]}
    except Exception as e:
        logger.error(f"daily-check shopify failed: {e}", exc_info=True)
        shopify_step = {"step": "shopify_orders", "status": "error", "error": str(e)}
    report["steps"].append(shopify_step)

    # ── Step 4: First-sale auto-trigger ──────────────────────────
    first_sale_step = {"step": "first_sale_check", "status": "no_action"}
    try:
        has_buyers = shopify_step.get("customers_with_orders", 0) > 0
        roas_row = db.query(SettingsModel).filter(SettingsModel.key == "min_roas_threshold").first()
        current_threshold = float(roas_row.value) if roas_row and roas_row.value else None

        if has_buyers and current_threshold is not None and current_threshold == 0:
            roas_row.value = "1.5"
            db.add(roas_row)
            db.commit()

            db.add(ActivityLogModel(
                action="FIRST_SALE_DETECTED",
                entity_type="system",
                details=f"Daily-check found {shopify_step.get('customers_with_orders')} customers with orders. "
                        f"Revenue: ${shopify_step.get('total_revenue', 0)}. "
                        f"Exiting awareness mode: min_roas_threshold 0 → 1.5",
            ))
            db.commit()

            first_sale_step = {
                "step": "first_sale_check",
                "status": "triggered",
                "previous_threshold": 0,
                "new_threshold": 1.5,
                "buyers_found": shopify_step.get("customers_with_orders", 0),
            }
            logger.info("daily-check: First sale detected — exited awareness mode, min_roas_threshold → 1.5")
        else:
            first_sale_step = {
                "step": "first_sale_check",
                "status": "no_action",
                "reason": "threshold already set" if (current_threshold and current_threshold > 0) else "no buyers yet",
                "current_threshold": current_threshold,
                "has_buyers": has_buyers,
            }
    except Exception as e:
        logger.error(f"daily-check first-sale check failed: {e}", exc_info=True)
        first_sale_step = {"step": "first_sale_check", "status": "error", "error": str(e)}
    report["steps"].append(first_sale_step)

    # ── Step 5: Safety limits ────────────────────────────────────
    try:
        safety = _check_safety_limits(db)
        report["steps"].append({"step": "safety_check", "status": "ok", **safety})
    except Exception as e:
        report["steps"].append({"step": "safety_check", "status": "error", "error": str(e)})

    # ── Finalize ─────────────────────────────────────────────────
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    report["elapsed_seconds"] = round(elapsed, 2)

    # Summary counts
    ok_steps = sum(1 for s in report["steps"] if s.get("status") == "ok")
    err_steps = sum(1 for s in report["steps"] if s.get("status") == "error")
    report["summary"] = f"{ok_steps}/{len(report['steps'])} steps OK" + (f", {err_steps} errors" if err_steps else "")

    # Log the run
    db.add(ActivityLogModel(
        action="DAILY_CHECK",
        entity_type="system",
        details=json.dumps(report, default=str)[:2000],
    ))
    db.commit()

    return report
