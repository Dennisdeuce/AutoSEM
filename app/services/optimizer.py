"""
Campaign Optimizer Service
Analyzes campaign performance and makes automated optimization decisions.
"""
import logging
from datetime import datetime
from typing import List, Dict
from sqlalchemy.orm import Session
from app.database import CampaignModel, SettingsModel, ActivityLogModel

logger = logging.getLogger("autosem.optimizer")


class CampaignOptimizer:
    MIN_IMPRESSIONS_FOR_DECISION = 100
    MIN_CLICKS_FOR_DECISION = 10
    LOW_CTR_THRESHOLD = 0.005
    HIGH_CTR_THRESHOLD = 0.03
    LOW_CONVERSION_RATE = 0.01
    BUDGET_INCREASE_FACTOR = 1.25
    BUDGET_DECREASE_FACTOR = 0.75
    MAX_DAILY_BUDGET = 50.0
    MIN_DAILY_BUDGET = 3.0

    def __init__(self, db: Session = None):
        self.db = db
        self.settings = {
            "daily_spend_limit": 200.0,
            "monthly_spend_limit": 5000.0,
            "min_roas_threshold": 1.5,
            "emergency_pause_loss": 500.0,
        }

    def optimize_all(self, db: Session = None) -> Dict:
        if db:
            self.db = db
        campaigns = self.db.query(CampaignModel).filter(
            CampaignModel.status.in_(["active", "ACTIVE", "live"])
        ).all()
        if not campaigns:
            return {"optimized": 0, "actions": [], "message": "No active campaigns"}

        actions = []
        for campaign in campaigns:
            campaign_actions = self._optimize_campaign(campaign)
            actions.extend(campaign_actions)

        safety_actions = self._check_safety_limits(campaigns)
        actions.extend(safety_actions)
        self.db.commit()

        return {"optimized": len(campaigns), "actions": actions, "timestamp": datetime.utcnow().isoformat()}

    def _optimize_campaign(self, campaign: CampaignModel) -> List[Dict]:
        actions = []
        impressions = getattr(campaign, 'impressions', 0) or 0
        clicks = getattr(campaign, 'clicks', 0) or 0
        conversions = campaign.conversions or 0
        spend = campaign.total_spend or campaign.spend or 0
        revenue = campaign.total_revenue or campaign.revenue or 0

        if impressions < self.MIN_IMPRESSIONS_FOR_DECISION:
            return [{"campaign_id": campaign.id, "action": "waiting", "reason": f"Insufficient data ({impressions} impressions)"}]

        ctr = clicks / impressions if impressions > 0 else 0
        roas = revenue / spend if spend > 0 else 0
        cpc = spend / clicks if clicks > 0 else 0

        if spend > 20:
            if roas >= self.settings["min_roas_threshold"] * 1.5:
                new_budget = min((campaign.daily_budget or 10) * self.BUDGET_INCREASE_FACTOR, self.MAX_DAILY_BUDGET)
                if new_budget != campaign.daily_budget:
                    old_budget = campaign.daily_budget
                    campaign.daily_budget = round(new_budget, 2)
                    actions.append({"campaign_id": campaign.id, "action": "budget_increase",
                                    "reason": f"Strong ROAS ({roas:.2f}x), budget {old_budget} -> {new_budget:.2f}"})

            elif roas < self.settings["min_roas_threshold"] and spend > 50:
                new_budget = max((campaign.daily_budget or 10) * self.BUDGET_DECREASE_FACTOR, self.MIN_DAILY_BUDGET)
                old_budget = campaign.daily_budget
                campaign.daily_budget = round(new_budget, 2)
                actions.append({"campaign_id": campaign.id, "action": "budget_decrease",
                                "reason": f"Low ROAS ({roas:.2f}x), budget {old_budget} -> {new_budget:.2f}"})

            elif roas < 0.5 and spend > 100:
                campaign.status = "PAUSED"
                actions.append({"campaign_id": campaign.id, "action": "paused",
                                "reason": f"Very low ROAS ({roas:.2f}x) after ${spend:.2f} spend"})

        if clicks >= self.MIN_CLICKS_FOR_DECISION:
            if ctr < self.LOW_CTR_THRESHOLD:
                actions.append({"campaign_id": campaign.id, "action": "flag_low_ctr",
                                "reason": f"CTR {ctr:.3%} below threshold"})

        campaign.updated_at = datetime.utcnow()

        if not actions:
            actions.append({"campaign_id": campaign.id, "action": "no_change",
                            "reason": f"Performance within targets (ROAS: {roas:.2f}x, CTR: {ctr:.2%})"})
        return actions

    def _check_safety_limits(self, campaigns: List[CampaignModel]) -> List[Dict]:
        actions = []
        total_daily_budget = sum(c.daily_budget or 0 for c in campaigns)
        total_spend = sum(c.total_spend or c.spend or 0 for c in campaigns)
        total_revenue = sum(c.total_revenue or c.revenue or 0 for c in campaigns)

        if total_daily_budget > self.settings["daily_spend_limit"]:
            scale_factor = self.settings["daily_spend_limit"] / total_daily_budget
            for c in campaigns:
                if c.daily_budget:
                    c.daily_budget = round(c.daily_budget * scale_factor, 2)
            actions.append({"action": "global_budget_scale",
                            "reason": f"Total budget ${total_daily_budget:.2f} exceeds limit, scaled by {scale_factor:.2f}"})

        net_loss = total_spend - total_revenue
        if net_loss > self.settings["emergency_pause_loss"]:
            for c in campaigns:
                c.status = "PAUSED"
            actions.append({"action": "emergency_pause_all",
                            "reason": f"Net loss ${net_loss:.2f} exceeds emergency threshold"})
        return actions

    def get_optimization_summary(self) -> Dict:
        campaigns = self.db.query(CampaignModel).all()
        total_spend = sum(c.total_spend or c.spend or 0 for c in campaigns)
        total_revenue = sum(c.total_revenue or c.revenue or 0 for c in campaigns)
        active = [c for c in campaigns if c.status in ("active", "ACTIVE", "live")]
        return {
            "total_campaigns": len(campaigns),
            "active": len(active),
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "overall_roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0,
        }
