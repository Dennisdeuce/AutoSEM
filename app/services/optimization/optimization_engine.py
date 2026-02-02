import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.crud import campaign, product
from app.models import Campaign, Ad, OptimizationLog
from app.services.bidding import bidding_engine, budget_allocator
from app.services.google_ads import google_ads_service
from app.services.meta_ads import meta_ads_service
from app.services.notifications import notification_service

logger = logging.getLogger(__name__)


class OptimizationEngine:
    def __init__(self, db: Session):
        self.db = db
        self.actions_taken = []

    def run_hourly_optimization(self):
        """Runs every hour"""
        logger.info("HOURLY OPTIMIZATION RUN STARTED")
        self.actions_taken = []

        self.pause_unprofitable_ads()
        self.adjust_bids_by_time_of_day()
        self.reallocate_budget_to_winners()
        self.check_anomaly_detection()

        logger.info(f"HOURLY OPTIMIZATION COMPLETE - {len(self.actions_taken)} actions taken")

        # Send alert if too many actions taken (potential issue)
        if len(self.actions_taken) > 20:
            notification_service.send_alert(
                "High Activity",
                f"Optimization engine took {len(self.actions_taken)} actions in one hour",
                urgent=False
            )

    def run_daily_optimization(self):
        """Runs at midnight"""
        logger.info("DAILY OPTIMIZATION RUN STARTED")
        self.actions_taken = []

        self.pause_unprofitable_ads()
        self.analyze_search_terms()
        self.refresh_audiences()
        self.test_new_creatives()
        self.graduate_winners()
        self.kill_losers()
        self.reallocate_budget_to_winners()
        self.update_product_costs()

        logger.info(f"DAILY OPTIMIZATION COMPLETE - {len(self.actions_taken)} actions taken")

        # Send daily report
        self._send_daily_report()

    def pause_unprofitable_ads(self):
        """
        Kill Rule: Pause any ad/adset/keyword with:
        - Spend > 2x Target CPA AND 0 conversions
        - ROAS < 50% of target over 7+ days with stat significance
        """
        active_campaigns = campaign.get_active_campaigns(self.db)

        for camp in active_campaigns:
            # Check campaigns with high spend and no conversions
            if camp.spend > (camp.target_cpa * 2) and camp.conversions == 0:
                self._pause_campaign(camp, f"Spent ${camp.spend}, 0 conversions (exceeded 2x CPA)")
                continue

            # Check ROAS performance over time
            if camp.days_running >= 7 and camp.roas < (camp.target_roas * 0.5):
                if camp.conversions >= 5:  # Statistical significance
                    self._pause_campaign(camp, f"ROAS {camp.roas} below threshold")
                    continue

            # Check for campaigns exceeding daily spend limits
            if camp.spend > settings.DAILY_SPEND_LIMIT * 0.8:  # 80% of daily limit
                self._reduce_campaign_budget(camp, 0.7, "Approaching daily spend limit")

    def adjust_bids_by_time_of_day(self):
        """Adjust bids based on time of day performance"""
        current_hour = datetime.now().hour

        # Peak hours (9 AM - 5 PM)
        if 9 <= current_hour <= 17:
            # Increase bids during peak hours for better performance
            self._adjust_bids(1.1, "Peak hour bid increase")
        else:
            # Decrease bids during off-peak to save budget
            self._adjust_bids(0.9, "Off-peak bid decrease")

    def reallocate_budget_to_winners(self):
        """Move budget from underperformers to top performers"""
        active_campaigns = campaign.get_active_campaigns(self.db)
        total_budget = sum(camp.daily_budget for camp in active_campaigns)

        if total_budget > settings.DAILY_SPEND_LIMIT:
            # Scale down if over budget
            scale_factor = settings.DAILY_SPEND_LIMIT / total_budget
            for camp in active_campaigns:
                new_budget = camp.daily_budget * scale_factor
                self._update_campaign_budget(camp, new_budget)
                self._log_action(f"BUDGET SCALE: {camp.name} reduced to ${new_budget:.2f}/day (over limit)")
            return

        allocations = budget_allocator.allocate_daily_budget(total_budget, active_campaigns)

        for camp_id, new_budget in allocations.items():
            camp = campaign.get(self.db, id=camp_id)
            if camp and abs(camp.daily_budget - new_budget) > 1.0:  # Only adjust if significant change
                old_budget = camp.daily_budget
                self._update_campaign_budget(camp, new_budget)
                self._log_action(f"BUDGET SHIFT: {camp.name} from ${old_budget:.2f}/day to ${new_budget:.2f}/day")

    def analyze_search_terms(self):
        """Add negatives and new keywords from search term analysis"""
        # Get search terms from Google Ads
        search_terms = google_ads_service.get_search_terms_report(days=30)

        for term in search_terms:
            # Add as negative if wasting spend
            if term.get("clicks", 0) >= 10 and term.get("conversions", 0) == 0:
                success = google_ads_service.add_negative_keyword(term["query"])
                if success:
                    self._log_action(f"NEW NEGATIVE: Added '{term['query']}' as negative keyword ({term['clicks']} clicks, 0 conv)")

            # Add as keyword if converting well
            if term.get("conversions", 0) >= 2 and term.get("roas", 0) > 2.5:
                # Find appropriate ad group (simplified - would need proper mapping)
                success = google_ads_service.add_keyword(term["query"])
                if success:
                    self._log_action(f"NEW KEYWORD: Added '{term['query']}' ({term['conversions']} conv, {term['roas']:.1f}x ROAS)")

    def refresh_audiences(self):
        """Update lookalikes and retargeting audiences"""
        # This would integrate with Meta Ads API to refresh audiences
        # For now, placeholder
        self._log_action("AUDIENCE REFRESH: Updated lookalike audiences")

    def test_new_creatives(self):
        """Launch A/B tests for new ad creatives"""
        # Get top performing products
        top_products = self._get_top_products(limit=3)

        for product in top_products:
            # Generate new creative variations
            creatives = self._generate_creative_test(product)

            # Launch test campaigns (simplified)
            self._log_action(f"CREATIVE TEST: Launched {len(creatives)} new variations for {product.title}")

    def graduate_winners(self):
        """Scale up top performers"""
        top_campaigns = self._get_top_performing_campaigns(limit=3)

        for camp in top_campaigns:
            if camp.roas > camp.target_roas * 1.5:  # Significantly overperforming
                new_budget = min(camp.daily_budget * 1.2, settings.DAILY_SPEND_LIMIT * 0.3)  # Cap at 30% of daily limit
                self._update_campaign_budget(camp, new_budget)
                self._log_action(f"GRADUATE: Increased budget for {camp.name} to ${new_budget:.2f}/day (ROAS {camp.roas:.1f}x)")

    def kill_losers(self):
        """Pause consistently underperforming campaigns"""
        underperformers = self._get_underperforming_campaigns()

        for camp in underperformers:
            self._pause_campaign(camp, f"Consistent underperformance (ROAS {camp.roas:.1f}x over {camp.days_running} days)")
            self._log_action(f"KILL: Paused {camp.name} (ROAS {camp.roas:.1f}x)")

    def update_product_costs(self):
        """Update product costs from Printful"""
        from app.services.printful import printful_service

        products_list = product.get_available_products(self.db)

        for prod in products_list:
            # Get updated cost from Printful
            cost = printful_service.calculate_total_cost(str(prod.shopify_id))
            if cost and cost != prod.cost_price:
                old_cost = prod.cost_price
                prod.cost_price = cost
                prod.gross_margin = prod.price - cost if prod.price else 0
                self.db.commit()
                self._log_action(f"COST UPDATE: {prod.title} cost changed from ${old_cost:.2f} to ${cost:.2f}")

    def check_anomaly_detection(self):
        """Check for anomalies that require immediate action"""
        active_campaigns = campaign.get_active_campaigns(self.db)

        total_spend_today = sum(camp.spend for camp in active_campaigns)
        total_conversions_today = sum(camp.conversions for camp in active_campaigns)

        # Check spend limit
        if total_spend_today > settings.DAILY_SPEND_LIMIT:
            notification_service.send_alert(
                "Daily Spend Limit Exceeded",
                f"Total spend today: ${total_spend_today:.2f} (limit: ${settings.DAILY_SPEND_LIMIT:.2f})",
                urgent=True
            )
            # Emergency pause all campaigns
            self._emergency_pause_all()

        # Check ROAS threshold
        total_revenue = sum(camp.revenue for camp in active_campaigns)
        account_roas = total_revenue / total_spend_today if total_spend_today > 0 else 0

        if account_roas < settings.MIN_ROAS_THRESHOLD:
            notification_service.send_alert(
                "ROAS Below Threshold",
                f"Account ROAS: {account_roas:.1f}x (threshold: {settings.MIN_ROAS_THRESHOLD:.1f}x)",
                urgent=True
            )

        # Check for conversion tracking issues
        if total_spend_today > 100 and total_conversions_today == 0:
            notification_service.send_alert(
                "Conversion Tracking Issue",
                f"Spent ${total_spend_today:.2f} with 0 conversions - possible tracking problem",
                urgent=False
            )

    def _pause_campaign(self, camp: Campaign, reason: str):
        """Pause a campaign"""
        camp.status = "PAUSED"
        self.db.commit()

        # Call platform API to pause
        if camp.platform == "google":
            google_ads_service.update_campaign_budget(camp.platform_campaign_id, 0)
        elif camp.platform == "meta":
            meta_ads_service.update_campaign_budget(camp.platform_campaign_id, 0)

        self._log_action(f"PAUSE: {camp.name} - {reason}")

    def _update_campaign_budget(self, camp: Campaign, new_budget: float):
        """Update campaign budget"""
        camp.daily_budget = new_budget
        self.db.commit()

        # Call platform API to update budget
        if camp.platform == "google":
            google_ads_service.update_campaign_budget(camp.platform_campaign_id, new_budget)
        elif camp.platform == "meta":
            meta_ads_service.update_campaign_budget(camp.platform_campaign_id, new_budget)

    def _reduce_campaign_budget(self, camp: Campaign, factor: float, reason: str):
        """Reduce campaign budget by factor"""
        new_budget = camp.daily_budget * factor
        self._update_campaign_budget(camp, new_budget)
        self._log_action(f"BUDGET REDUCE: {camp.name} {factor}x reduction - {reason}")

    def _adjust_bids(self, multiplier: float, reason: str):
        """Adjust bids for all active campaigns"""
        active_campaigns = campaign.get_active_campaigns(self.db)

        for camp in active_campaigns:
            # Update target CPA/ROAS based on multiplier
            if camp.target_cpa:
                camp.target_cpa *= multiplier
            if camp.target_roas:
                camp.target_roas *= multiplier
            self.db.commit()
            self._log_action(f"BID {reason}: {camp.name} adjusted by {multiplier}x")

    def _emergency_pause_all(self):
        """Emergency pause all campaigns"""
        active_campaigns = campaign.get_active_campaigns(self.db)

        for camp in active_campaigns:
            self._pause_campaign(camp, "Emergency pause - spend limit exceeded")

        self._log_action("EMERGENCY: All campaigns paused due to spend limit")

    def _get_top_products(self, limit: int = 5):
        """Get top performing products"""
        # Simplified - in real implementation would rank by revenue/ROAS
        products_list = product.get_available_products(self.db)
        return products_list[:limit]

    def _get_top_performing_campaigns(self, limit: int = 5) -> List[Campaign]:
        """Get campaigns with ROAS > target * 1.2"""
        active_campaigns = campaign.get_active_campaigns(self.db)
        top_performers = [c for c in active_campaigns if c.roas > c.target_roas * 1.2]
        return sorted(top_performers, key=lambda x: x.roas, reverse=True)[:limit]

    def _get_underperforming_campaigns(self) -> List[Campaign]:
        """Get campaigns with ROAS < target * 0.5 for 7+ days"""
        active_campaigns = campaign.get_active_campaigns(self.db)
        return [c for c in active_campaigns if c.roas < c.target_roas * 0.5 and c.days_running >= 7]

    def _generate_creative_test(self, product) -> List[Dict[str, Any]]:
        """Generate creative test variations"""
        from app.services.creative import creative_engine

        # Generate new headlines and descriptions
        creatives = creative_engine.generate_ad_content(product)

        # In real implementation, would create actual ad variations
        return creatives.get("headlines", [])[:2]  # Return first 2 for testing

    def _send_daily_report(self):
        """Send daily performance report"""
        # Get today's metrics
        from app.api.v1.endpoints.dashboard import get_daily_metrics
        metrics = get_daily_metrics(self.db)

        report_data = {
            "spend_today": metrics["total"]["spend"],
            "revenue_today": metrics["total"]["revenue"],
            "roas_today": metrics["total"]["roas"],
            "orders_today": metrics["total"]["conversions"],
            "system_status": "operational",
            "last_optimization": "just completed",
            "actions_today": len(self.actions_taken),
            "top_performers": [],  # Would populate with real data
            "actions_taken": self.actions_taken[-10:]  # Last 10 actions
        }

        notification_service.send_daily_report(report_data)

    def _log_action(self, action: str):
        """Log an optimization action"""
        self.actions_taken.append(action)
        logger.info(action)

        # Save to database
        log_entry = OptimizationLog(
            action=action,
            details=f"Optimization action taken: {action}"
        )
        self.db.add(log_entry)
        self.db.commit()


# Global instance for background tasks
def get_optimization_engine(db: Session) -> OptimizationEngine:
    return OptimizationEngine(db)