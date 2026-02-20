"""AutoSEM Scheduler
Runs periodic optimization cycles, performance syncs, and spend checks.
Writes heartbeat timestamps to SettingsModel after each job.
Logs start/end of each job to ActivityLogModel.

Phase 8: Jobs use SessionLocal() directly instead of HTTP self-calls.
Phase 11: Added midnight CST optimization cron, hourly spend check, tick logging.
"""
import json
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

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
    """Execute a full optimization cycle with a proper DB session."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled optimization cycle")
    _log_job_activity("SCHEDULER_JOB_START", "optimization_cycle started")

    status = "ok"
    error_msg = ""
    results = None

    from app.database import SessionLocal, ActivityLogModel
    db = SessionLocal()
    try:
        from app.services.optimizer import CampaignOptimizer
        optimizer = CampaignOptimizer(db)
        results = optimizer.optimize_all()
        logger.info(f"Optimization cycle completed: {len(results) if results else 0} actions")

        # Log result to activity log
        activity = ActivityLogModel(
            action="SCHEDULER_OPTIMIZE",
            entity_type="scheduler",
            entity_id="",
            details=json.dumps(results, default=str) if results else "No actions taken",
        )
        db.add(activity)
        db.commit()
    except Exception as e:
        status = "error"
        error_msg = str(e)
        logger.error(f"Scheduled optimization failed: {e}")
        db.rollback()
        try:
            activity = ActivityLogModel(
                action="SCHEDULER_ERROR",
                entity_type="scheduler",
                entity_id="",
                details=f"Optimization failed: {error_msg}",
            )
            db.add(activity)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
        _write_heartbeat("last_optimization")
        end_ts = datetime.now(timezone.utc).isoformat()
        _log_job_activity("SCHEDULER_JOB_END", f"optimization_cycle finished ({status}){': ' + error_msg if error_msg else ''}")
        logger.info(f"[{end_ts}] Optimization cycle finished ({status})")


def sync_performance():
    """Sync performance data from ad platforms with a proper DB session."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled performance sync")
    _log_job_activity("SCHEDULER_JOB_START", "sync_performance started")

    status = "ok"
    error_msg = ""

    from app.database import SessionLocal, ActivityLogModel
    db = SessionLocal()
    try:
        from app.services.performance_sync import PerformanceSyncService
        sync_service = PerformanceSyncService(db)
        result = sync_service.sync_all()
        logger.info(f"Performance sync completed: {result}")

        activity = ActivityLogModel(
            action="SCHEDULER_SYNC",
            entity_type="scheduler",
            entity_id="",
            details=json.dumps(result, default=str) if result else "Sync completed",
        )
        db.add(activity)
        db.commit()
    except Exception as e:
        status = "error"
        error_msg = str(e)
        logger.error(f"Scheduled performance sync failed: {e}")
        db.rollback()
        try:
            activity = ActivityLogModel(
                action="SCHEDULER_ERROR",
                entity_type="scheduler",
                entity_id="",
                details=f"Performance sync failed: {error_msg}",
            )
            db.add(activity)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
        _write_heartbeat("last_sync_performance")
        end_ts = datetime.now(timezone.utc).isoformat()
        _log_job_activity("SCHEDULER_JOB_END", f"sync_performance finished ({status}){': ' + error_msg if error_msg else ''}")
        logger.info(f"[{end_ts}] Performance sync finished ({status})")


def check_hourly_spend():
    """Hourly spend check: query active campaign budgets vs daily_spend_limit.

    If total active daily budgets exceed the limit, log a SPEND_ALERT.
    Uses NotificationService to record alerts.
    """
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] TICK: hourly_spend_check")
    _log_job_activity("SCHEDULER_TICK", "hourly_spend_check")

    from app.database import SessionLocal, CampaignModel, SettingsModel
    db = SessionLocal()
    try:
        # Get daily spend limit from settings
        limit_row = db.query(SettingsModel).filter(SettingsModel.key == "daily_spend_limit").first()
        daily_limit = float(limit_row.value) if limit_row and limit_row.value else 200.0

        # Sum daily budgets of active campaigns
        active_campaigns = db.query(CampaignModel).filter(
            CampaignModel.status.in_(["active", "live", "ACTIVE"])
        ).all()
        total_daily_budget = sum(c.daily_budget or 0 for c in active_campaigns)
        total_spend_today = sum(c.total_spend or 0 for c in active_campaigns)

        utilization = (total_daily_budget / daily_limit * 100) if daily_limit > 0 else 0

        logger.info(
            f"Spend check: {len(active_campaigns)} active campaigns, "
            f"daily budget ${total_daily_budget:.2f} / ${daily_limit:.2f} limit "
            f"({utilization:.0f}% utilized), total spend ${total_spend_today:.2f}"
        )

        # Alert if over 90% of daily limit
        if total_daily_budget > daily_limit * 0.9:
            from app.services.notifications import NotificationService
            notifier = NotificationService(db)
            notifier.notify_spend_alert(
                "ALL_CAMPAIGNS",
                total_daily_budget,
                daily_limit,
            )
            logger.warning(
                f"SPEND ALERT: Total daily budget ${total_daily_budget:.2f} "
                f"exceeds 90% of ${daily_limit:.2f} limit"
            )
    except Exception as e:
        logger.error(f"Hourly spend check failed: {e}")
        db.rollback()
    finally:
        db.close()
        _write_heartbeat("last_spend_check")


def scheduler_tick():
    """Lightweight tick logged every hour to prove scheduler is alive."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] TICK: scheduler heartbeat")
    _log_job_activity("SCHEDULER_TICK", f"heartbeat at {ts}")
    _write_heartbeat("last_scheduler_tick")


def start_scheduler():
    """Start the background scheduler."""
    # Daily optimization at midnight CST (06:00 UTC)
    scheduler.add_job(
        run_optimization_cycle,
        trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="daily_optimization",
        name="Daily Optimization (midnight CST)",
        replace_existing=True,
    )

    # Also keep the 6-hour interval optimization for intra-day checks
    scheduler.add_job(
        run_optimization_cycle,
        trigger=IntervalTrigger(hours=6),
        id="optimization_cycle",
        name="AutoSEM Optimization Cycle (6h)",
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

    # Hourly spend check
    scheduler.add_job(
        check_hourly_spend,
        trigger=IntervalTrigger(hours=1),
        id="hourly_spend_check",
        name="Hourly Spend Check",
        replace_existing=True,
    )

    # Hourly scheduler tick (heartbeat proof-of-life)
    scheduler.add_job(
        scheduler_tick,
        trigger=IntervalTrigger(hours=1, start_date=datetime.now(timezone.utc)),
        id="scheduler_tick",
        name="Scheduler Heartbeat Tick",
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
