"""AutoSEM Scheduler
Runs periodic optimization cycles and performance syncs.
Writes heartbeat timestamps to SettingsModel after each job.
Logs start/end of each job to ActivityLogModel.
"""
import os
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("autosem.scheduler")

scheduler = BackgroundScheduler()


def _write_heartbeat(key: str):
    """Write an ISO timestamp to SettingsModel for the given key."""
    try:
        from app.database import SessionLocal, SettingsModel
        db = SessionLocal()
        try:
            setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
            ts = datetime.now(timezone.utc).isoformat()
            if setting:
                setting.value = ts
            else:
                setting = SettingsModel(key=key, value=ts)
                db.add(setting)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to write heartbeat '{key}': {e}")


def _log_job_activity(action: str, details: str):
    """Log a scheduler job event to ActivityLogModel."""
    try:
        from app.database import SessionLocal, ActivityLogModel
        db = SessionLocal()
        try:
            log = ActivityLogModel(
                action=action,
                entity_type="scheduler",
                entity_id="",
                details=details,
            )
            db.add(log)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to log job activity: {e}")


def run_optimization_cycle():
    """Execute a full optimization cycle."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled optimization cycle")
    _log_job_activity("SCHEDULER_JOB_START", "optimization_cycle started")

    status = "ok"
    error_msg = ""
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/v1/automation/run-cycle", timeout=120)
        logger.info(f"Optimization cycle result: {response.status_code}")
    except Exception as e:
        status = "error"
        error_msg = str(e)
        logger.error(f"Scheduled optimization failed: {e}")
    finally:
        _write_heartbeat("last_optimization")
        end_ts = datetime.now(timezone.utc).isoformat()
        _log_job_activity("SCHEDULER_JOB_END", f"optimization_cycle finished ({status}){': ' + error_msg if error_msg else ''}")
        logger.info(f"[{end_ts}] Optimization cycle finished ({status})")


def sync_performance():
    """Sync performance data from ad platforms."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled performance sync")
    _log_job_activity("SCHEDULER_JOB_START", "sync_performance started")

    status = "ok"
    error_msg = ""
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/v1/automation/sync-performance", timeout=60)
        logger.info(f"Performance sync result: {response.status_code}")
    except Exception as e:
        status = "error"
        error_msg = str(e)
        logger.error(f"Scheduled performance sync failed: {e}")
    finally:
        _write_heartbeat("last_sync_performance")
        end_ts = datetime.now(timezone.utc).isoformat()
        _log_job_activity("SCHEDULER_JOB_END", f"sync_performance finished ({status}){': ' + error_msg if error_msg else ''}")
        logger.info(f"[{end_ts}] Performance sync finished ({status})")


def start_scheduler():
    """Start the background scheduler."""
    # Run optimization every 6 hours
    scheduler.add_job(
        run_optimization_cycle,
        trigger=IntervalTrigger(hours=6),
        id="optimization_cycle",
        name="AutoSEM Optimization Cycle",
        replace_existing=True,
    )

    # Sync performance every 2 hours
    scheduler.add_job(
        sync_performance,
        trigger=IntervalTrigger(hours=2),
        id="performance_sync",
        name="Performance Data Sync",
        replace_existing=True,
    )

    # Refresh Shopify token every 20 hours (tokens expire in ~24h)
    try:
        from app.services.shopify_token import scheduled_token_refresh
        scheduler.add_job(
            scheduled_token_refresh,
            trigger=IntervalTrigger(hours=20),
            id="shopify_token_refresh",
            name="Shopify Token Refresh",
            replace_existing=True,
        )
    except Exception as e:
        logger.warning(f"Shopify token refresh job not loaded: {e}")

    scheduler.start()
    job_count = len(scheduler.get_jobs())
    logger.info(f"AutoSEM scheduler started with {job_count} jobs: " +
                ", ".join(j.name for j in scheduler.get_jobs()))


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AutoSEM scheduler stopped")
