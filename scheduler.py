"""
AutoSEM Scheduler
Runs periodic optimization cycles and performance syncs.
"""
import os
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("autosem.scheduler")

scheduler = BackgroundScheduler()


def run_optimization_cycle():
    """Execute a full optimization cycle."""
    logger.info(f"[{datetime.utcnow().isoformat()}] Running scheduled optimization cycle")
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/automation/run-cycle", timeout=120)
        logger.info(f"Optimization cycle result: {response.status_code}")
    except Exception as e:
        logger.error(f"Scheduled optimization failed: {e}")


def sync_performance():
    """Sync performance data from ad platforms."""
    logger.info(f"[{datetime.utcnow().isoformat()}] Running scheduled performance sync")
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/automation/sync-performance", timeout=60)
        logger.info(f"Performance sync result: {response.status_code}")
    except Exception as e:
        logger.error(f"Scheduled performance sync failed: {e}")


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        run_optimization_cycle,
        trigger=IntervalTrigger(hours=6),
        id="optimization_cycle",
        name="AutoSEM Optimization Cycle",
        replace_existing=True,
    )
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
