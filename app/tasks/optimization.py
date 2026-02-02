from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.optimization import get_optimization_engine


@celery_app.task
def run_hourly_optimization():
    """Run hourly optimization"""
    db = SessionLocal()
    try:
        engine = get_optimization_engine(db)
        engine.run_hourly_optimization()
    finally:
        db.close()


@celery_app.task
def run_daily_optimization():
    """Run daily optimization"""
    db = SessionLocal()
    try:
        engine = get_optimization_engine(db)
        engine.run_daily_optimization()
    finally:
        db.close()


@celery_app.task
def send_daily_report():
    """Send daily performance report"""
    # Implementation would generate and send email/SMS report
    pass