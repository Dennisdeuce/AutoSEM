"""AutoSEM Scheduler
Runs periodic optimization cycles, performance syncs, and spend checks.
Writes heartbeat timestamps to SettingsModel after each job.
Logs start/end of each job to ActivityLogModel.

Phase 8: Jobs use SessionLocal() directly instead of HTTP self-calls.
Phase 11: Added midnight CST optimization cron, hourly spend check, tick logging.
Phase 13: Retry with exponential backoff, job tracking, /health/scheduler endpoint,
          force-sync endpoint, SYNC_FAILURE_CRITICAL alerting.
"""
import json
import logging
import time
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("autosem.scheduler")

scheduler = BackgroundScheduler()

# ─── Job Tracking ────────────────────────────────────────────────
# Module-level dict tracking last successful run and failure counts per job
job_tracking = {
    # "job_name": {"last_success": <iso_str>, "last_run": <iso_str>,
    #              "last_error": <str>, "consecutive_failures": 0, "total_runs": 0}
}

_RETRY_DELAYS = [5, 15, 45]  # seconds for exponential backoff


def _init_tracking(job_name: str):
    if job_name not in job_tracking:
        job_tracking[job_name] = {
            "last_success": None,
            "last_run": None,
            "last_error": None,
            "consecutive_failures": 0,
            "total_runs": 0,
        }


def _track_success(job_name: str):
    _init_tracking(job_name)
    now = datetime.now(timezone.utc).isoformat()
    job_tracking[job_name]["last_success"] = now
    job_tracking[job_name]["last_run"] = now
    job_tracking[job_name]["consecutive_failures"] = 0
    job_tracking[job_name]["total_runs"] += 1


def _track_failure(job_name: str, error: str):
    _init_tracking(job_name)
    now = datetime.now(timezone.utc).isoformat()
    job_tracking[job_name]["last_run"] = now
    job_tracking[job_name]["last_error"] = error
    job_tracking[job_name]["consecutive_failures"] += 1
    job_tracking[job_name]["total_runs"] += 1


def _run_with_retry(job_name: str, func, *args, **kwargs):
    """Run a function with 3 retry attempts and exponential backoff (5s, 15s, 45s)."""
    _init_tracking(job_name)
    last_exc = None
    for attempt, delay in enumerate(_RETRY_DELAYS):
        try:
            result = func(*args, **kwargs)
            _track_success(job_name)
            return result
        except Exception as e:
            last_exc = e
            logger.warning(f"[{job_name}] Attempt {attempt + 1}/3 failed: {e}")
            if attempt < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)

    # All retries exhausted
    error_msg = str(last_exc)
    _track_failure(job_name, error_msg)
    logger.error(f"[{job_name}] All 3 attempts failed: {error_msg}")

    # If sync_performance fails 3x consecutively, log SYNC_FAILURE_CRITICAL
    if job_name == "sync_performance" and job_tracking[job_name]["consecutive_failures"] >= 3:
        _log_job_activity("SYNC_FAILURE_CRITICAL",
                          f"sync_performance failed {job_tracking[job_name]['consecutive_failures']}x consecutively: {error_msg}")

    return None


# ─── Helpers ─────────────────────────────────────────────────────

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


# ─── Job Implementations ────────────────────────────────────────

def _do_optimization():
    """Core optimization logic (called within retry wrapper)."""
    from app.database import SessionLocal, ActivityLogModel
    db = SessionLocal()
    try:
        from app.services.optimizer import CampaignOptimizer
        optimizer = CampaignOptimizer(db)
        results = optimizer.optimize_all()
        logger.info(f"Optimization cycle completed: {len(results) if results else 0} actions")

        activity = ActivityLogModel(
            action="SCHEDULER_OPTIMIZE",
            entity_type="scheduler",
            entity_id="",
            details=json.dumps(results, default=str) if results else "No actions taken",
        )
        db.add(activity)
        db.commit()
        return results
    except Exception as e:
        db.rollback()
        try:
            activity = ActivityLogModel(
                action="SCHEDULER_ERROR",
                entity_type="scheduler",
                entity_id="",
                details=f"Optimization failed: {str(e)}",
            )
            db.add(activity)
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


def _do_sync_performance():
    """Core performance sync logic (called within retry wrapper)."""
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
        return result
    except Exception as e:
        db.rollback()
        try:
            activity = ActivityLogModel(
                action="SCHEDULER_ERROR",
                entity_type="scheduler",
                entity_id="",
                details=f"Performance sync failed: {str(e)}",
            )
            db.add(activity)
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


def run_optimization_cycle():
    """Execute a full optimization cycle with retry logic."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled optimization cycle")
    _log_job_activity("SCHEDULER_JOB_START", "optimization_cycle started")

    _run_with_retry("optimization_cycle", _do_optimization)

    _write_heartbeat("last_optimization")
    end_ts = datetime.now(timezone.utc).isoformat()
    _log_job_activity("SCHEDULER_JOB_END", f"optimization_cycle finished at {end_ts}")
    logger.info(f"[{end_ts}] Optimization cycle finished")


def sync_performance():
    """Sync performance data from ad platforms with retry logic."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Starting scheduled performance sync")
    _log_job_activity("SCHEDULER_JOB_START", "sync_performance started")

    _run_with_retry("sync_performance", _do_sync_performance)

    _write_heartbeat("last_sync_performance")
    end_ts = datetime.now(timezone.utc).isoformat()
    _log_job_activity("SCHEDULER_JOB_END", f"sync_performance finished at {end_ts}")
    logger.info(f"[{end_ts}] Performance sync finished")


def run_daily_snapshot():
    """Take a daily performance snapshot after optimization."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] Taking daily performance snapshot")
    _log_job_activity("SCHEDULER_JOB_START", "daily_snapshot started")

    def _do_snapshot():
        from app.database import SessionLocal, CampaignModel
        db = SessionLocal()
        try:
            from app.database import PerformanceSnapshotModel
            from datetime import date
            today = date.today()
            campaigns = db.query(CampaignModel).filter(
                CampaignModel.status.in_(["active", "ACTIVE", "live"])
            ).all()
            count = 0
            for c in campaigns:
                # Check if snapshot already exists for today
                existing = db.query(PerformanceSnapshotModel).filter(
                    PerformanceSnapshotModel.date == today,
                    PerformanceSnapshotModel.campaign_id == c.id,
                ).first()
                if existing:
                    continue
                snap = PerformanceSnapshotModel(
                    date=today,
                    platform=c.platform or "unknown",
                    campaign_id=c.id,
                    spend=c.spend or 0,
                    clicks=c.clicks or 0,
                    impressions=c.impressions or 0,
                    ctr=round((c.clicks / c.impressions * 100) if c.impressions and c.impressions > 0 else 0, 2),
                    cpc=round((c.spend / c.clicks) if c.clicks and c.clicks > 0 else 0, 2),
                    conversions=c.conversions or 0,
                    revenue=c.revenue or 0,
                )
                db.add(snap)
                count += 1
            db.commit()
            logger.info(f"Daily snapshot: {count} campaign snapshots saved for {today}")
            return count
        finally:
            db.close()

    _run_with_retry("daily_snapshot", _do_snapshot)
    _write_heartbeat("last_daily_snapshot")


def check_hourly_spend():
    """Hourly spend check: query active campaign budgets vs daily_spend_limit."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] TICK: hourly_spend_check")
    _log_job_activity("SCHEDULER_TICK", "hourly_spend_check")

    def _do_spend_check():
        from app.database import SessionLocal, CampaignModel, SettingsModel
        db = SessionLocal()
        try:
            limit_row = db.query(SettingsModel).filter(SettingsModel.key == "daily_spend_limit").first()
            daily_limit = float(limit_row.value) if limit_row and limit_row.value else 200.0

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
        finally:
            db.close()

    _run_with_retry("hourly_spend_check", _do_spend_check)
    _write_heartbeat("last_spend_check")


def scheduler_tick():
    """Lightweight tick logged every hour to prove scheduler is alive."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{ts}] TICK: scheduler heartbeat")
    _log_job_activity("SCHEDULER_TICK", f"heartbeat at {ts}")
    _write_heartbeat("last_scheduler_tick")
    _track_success("scheduler_tick")


def force_sync_performance() -> dict:
    """Run performance sync immediately with verbose JSON output. Used by /automation/force-sync."""
    ts_start = datetime.now(timezone.utc).isoformat()
    try:
        from app.database import SessionLocal, ActivityLogModel
        from app.services.performance_sync import PerformanceSyncService
        db = SessionLocal()
        try:
            sync_service = PerformanceSyncService(db)
            result = sync_service.sync_all()
            _track_success("sync_performance")

            activity = ActivityLogModel(
                action="FORCE_SYNC",
                entity_type="scheduler",
                entity_id="",
                details=json.dumps(result, default=str) if result else "Force sync completed",
            )
            db.add(activity)
            db.commit()

            return {
                "status": "ok",
                "started": ts_start,
                "finished": datetime.now(timezone.utc).isoformat(),
                "results": result,
            }
        finally:
            db.close()
    except Exception as e:
        _track_failure("sync_performance", str(e))
        return {
            "status": "error",
            "started": ts_start,
            "finished": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def get_scheduler_health() -> dict:
    """Return scheduler health data for /health/scheduler endpoint."""
    jobs_info = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run,
            })

    return {
        "status": "running" if scheduler.running else "stopped",
        "jobs_registered": len(jobs_info),
        "jobs": jobs_info,
        "tracking": {k: v for k, v in job_tracking.items()},
    }


# ─── Scheduler Setup ────────────────────────────────────────────

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

    # Daily snapshot after midnight optimization
    scheduler.add_job(
        run_daily_snapshot,
        trigger=CronTrigger(hour=6, minute=15, timezone="UTC"),
        id="daily_snapshot",
        name="Daily Performance Snapshot",
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

    # Daily performance report at 08:00 UTC (2:00 AM CST)
    try:
        from app.services.daily_report import run_daily_report
        scheduler.add_job(
            run_daily_report,
            trigger=CronTrigger(hour=8, minute=0, timezone="UTC"),
            id="daily_report",
            name="Daily Performance Report (08:00 UTC)",
            replace_existing=True,
        )
    except Exception as e:
        logger.warning(f"Daily report job not loaded: {e}")

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
