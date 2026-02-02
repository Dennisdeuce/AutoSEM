#!/usr/bin/env python3
"""
AutoSEM Background Task Scheduler
Runs optimization tasks automatically without user intervention
"""

import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.optimization import optimization_engine
from app.services.shopify import shopify_service
from app.tasks import sync_data

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoSEMScheduler:
    """Scheduler for AutoSEM background tasks"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.db: Session = SessionLocal()

    async def start(self):
        """Start the scheduler"""
        logger.info("Starting AutoSEM Scheduler...")

        # Schedule optimization tasks
        self._schedule_optimization_tasks()

        # Schedule data sync tasks
        self._schedule_data_sync_tasks()

        # Start the scheduler
        self.scheduler.start()
        logger.info("AutoSEM Scheduler started successfully")

        # Keep the scheduler running
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down AutoSEM Scheduler...")
            self.scheduler.shutdown()
            self.db.close()

    def _schedule_optimization_tasks(self):
        """Schedule optimization-related tasks"""
        # Hourly optimization (every hour at :00)
        self.scheduler.add_job(
            self._run_hourly_optimization,
            trigger=CronTrigger(minute=0),
            id='hourly_optimization',
            name='Hourly Optimization',
            max_instances=1,
            replace_existing=True
        )

        # Daily optimization (every day at midnight)
        self.scheduler.add_job(
            self._run_daily_optimization,
            trigger=CronTrigger(hour=0, minute=0),
            id='daily_optimization',
            name='Daily Optimization',
            max_instances=1,
            replace_existing=True
        )

        # Emergency check (every 15 minutes)
        self.scheduler.add_job(
            self._run_emergency_check,
            trigger=CronTrigger(minute='*/15'),
            id='emergency_check',
            name='Emergency Check',
            max_instances=1,
            replace_existing=True
        )

        logger.info("Optimization tasks scheduled")

    def _schedule_data_sync_tasks(self):
        """Schedule data synchronization tasks"""
        # Sync Shopify data (every 30 minutes)
        self.scheduler.add_job(
            self._sync_shopify_data,
            trigger=CronTrigger(minute='*/30'),
            id='shopify_sync',
            name='Shopify Data Sync',
            max_instances=1,
            replace_existing=True
        )

        # Sync product costs (daily at 2 AM)
        self.scheduler.add_job(
            self._sync_product_costs,
            trigger=CronTrigger(hour=2, minute=0),
            id='cost_sync',
            name='Product Cost Sync',
            max_instances=1,
            replace_existing=True
        )

        logger.info("Data sync tasks scheduled")

    async def _run_hourly_optimization(self):
        """Run hourly optimization"""
        logger.info("Running scheduled hourly optimization")
        try:
            engine = optimization_engine.get_optimization_engine(self.db)
            engine.run_hourly_optimization()
            logger.info("Hourly optimization completed successfully")
        except Exception as e:
            logger.error(f"Error in hourly optimization: {str(e)}")

    async def _run_daily_optimization(self):
        """Run daily optimization"""
        logger.info("Running scheduled daily optimization")
        try:
            engine = optimization_engine.get_optimization_engine(self.db)
            engine.run_daily_optimization()
            logger.info("Daily optimization completed successfully")
        except Exception as e:
            logger.error(f"Error in daily optimization: {str(e)}")

    async def _run_emergency_check(self):
        """Run emergency checks"""
        logger.info("Running emergency check")
        try:
            engine = optimization_engine.get_optimization_engine(self.db)
            engine.check_anomaly_detection()
            logger.info("Emergency check completed successfully")
        except Exception as e:
            logger.error(f"Error in emergency check: {str(e)}")

    async def _sync_shopify_data(self):
        """Sync data from Shopify"""
        logger.info("Running Shopify data sync")
        try:
            await sync_data.sync_shopify_data()
            logger.info("Shopify data sync completed successfully")
        except Exception as e:
            logger.error(f"Error in Shopify data sync: {str(e)}")

    async def _sync_product_costs(self):
        """Sync product costs from Printful"""
        logger.info("Running product cost sync")
        try:
            await sync_data.sync_product_costs()
            logger.info("Product cost sync completed successfully")
        except Exception as e:
            logger.error(f"Error in product cost sync: {str(e)}")


async def main():
    """Main entry point"""
    scheduler = AutoSEMScheduler()
    await scheduler.start()


if __name__ == "__main__":
    # Run the scheduler
    asyncio.run(main())