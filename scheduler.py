"""AutoSEM Scheduler
Runs periodic optimization cycles and performance syncs.
Writes heartbeat timestamps to SettingsModel after each job.
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


def run_optimization_cycle():
    """Execute a full optimization cycle."""
    logger.info(f"[{datetime.utcnow().isoformat()}] Running scheduled optimization cycle")
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        # Bug 5 fix: correct URL path with /api/v1/ prefix
        response = httpx.post(f"{base_url}/api/v1/automation/run-cycle", timeout=120)
        logger.info(f"Optimization cycle result: {response.status_code}")
    except Exception as e:
        logger.error(f"Scheduled optimization failed: {e}")
    finally:
        _write_heartbeat("last_optimization")


def sync_performance():
    """Sync performance data from ad platforms."""
    logger.info(f"[{datetime.utcnow().isoformat()}] Running scheduled performance sync")
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        # Bug 5 fix: correct URL path with /api/v1/ prefix
        response = httpx.post(f"{base_url}/api/v1/automation/sync-performance", timeout=60)
        logger.info(f"Performance sync result: {response.status_code}")
    except Exception as e:
        logger.error(f"Scheduled performance sync failed: {e}")
    finally:
        _write_heartbeat("last_sync_performance")


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

    scheduler.start()
    logger.info("AutoSEM scheduler started")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AutoSEM scheduler stopped")
