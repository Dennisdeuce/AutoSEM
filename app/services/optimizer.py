"""
Campaign Optimizer Service
Analyzes campaign performance and makes automated optimization decisions.
Executes real actions via Meta Ads API (budget changes, pauses, scaling).
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.database import CampaignModel, SettingsModel, ActivityLogModel
from app.services.meta_ads import MetaAdsService

logger = logging.getLogger("autosem.optimizer")


class CampaignOptimizer:
    """Optimizes campaigns based on performance data."""

    MIN_IMPRESSIONS_FOR_DECISION = 100
    MIN_CLICKS_FOR_DECISION = 10
    LOW_CTR_THRESHOLD = 0.005
    HIGH_CTR_THRESHOLD = 0.03
    LOW_CONVERSION_RATE = 0.01
    BUDGET_INCREASE_FACTOR = 1.25
    BUDGET_DECREASE_FACTOR = 0.75
    MAX_DAILY_BUDGET = 50.0
    MIN_DAILY_BUDGET = 3.0
    SCALE_WINNER_MAX_BUDGET = 25.0
    SCALE_WINNER_INCREASE = 1.20  # +20%

    def __init__(self, db: Session):
        self.db = db
        self.meta = MetaAdsService()
        self.settings = self._load_settings()

    def _load_settings(self) -> dict:
        settings = self.db.query(SettingsModel).first()
        if settings:
            return {
                "daily_spend_limit": settings.daily_spend_limit,
                "monthly_spend_limit": settings.monthly_spend_limit,
                "min_roas_threshold": settings.min_roas_threshold,
                "emergency_pause_loss": settings.emergency_pause_loss,
            }
        return {
            "daily_spend_limit": 200.0,
            "monthly_spend_limit": 5000.0,
            "min_roas_threshold": 1.5,
            "emergency_pause_loss": 500.0,
        }

    def optimize_all(self) -> Dict:
        campaigns = self.db.query(CampaignModel).filter(
            CampaignModel.status.in_(["active", "live"])
        ).all()

        if not campaigns:
            return {"optimized": 0, "actions": [], "message": "No active campaigns to optimize"}

        actions = []
        for campaign in campaigns:
            campaign_actions = self._optimize_campaign(campaign)
            actions.extend(campaign_actions)

        safety_actions = self._check_safety_limits(campaigns)
        actions.extend(safety_actions)

        self.db.commit()

        return {
            "optimized": len(campaigns),
            "actions": actions,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _get_adset_id(self, campaign: CampaignModel) -> Optional[str]:
        """Resolve the first adset ID for a Meta campaign (needed for budget changes)."""
        if campaign.platform != "meta" or not campaign.platform_campaign_id:
            return None
        adsets = self.meta.get_adsets(campaign.platform_campaign_id)
        if adsets:
            return adsets[0].get("id")
        return None

    def _execute_meta_pause(self, campaign: CampaignModel, reason: str) -> Dict:
        """Pause a Meta campaign via the API and log the action."""
        result = {"executed": False}
        if campaign.platform == "meta" and campaign.platform_campaign_id:
            api_result = self.meta.pause_campaign(campaign.platform_campaign_id)
            result = {"executed": api_result.get("success", False), "api_result": api_result}
        campaign.status = "paused"
        self._log_auto_optimize(campaign, "pause", reason)
        return result

    def _execute_meta_budget_change(self, campaign: CampaignModel, new_budget: float, reason: str) -> Dict:
        """Change budget on a Meta campaign's adset via the API."""
        result = {"executed": False}
        if campaign.platform == "meta" and campaign.platform_campaign_id:
            adset_id = self._get_adset_id(campaign)
            if adset_id:
                api_result = self.meta.update_adset_budget(adset_id, new_budget)
                result = {"executed": api_result.get("success", False), "adset_id": adset_id, "api_result": api_result}
            else:
                logger.warning(f"No adset found for campaign {campaign.platform_campaign_id} — budget change local only")
        old_budget = campaign.daily_budget
        campaign.daily_budget = round(new_budget, 2)
        self._log_auto_optimize(campaign, "budget_change", f"{reason} (${old_budget} -> ${new_budget:.2f})")
        return result

    def _log_auto_optimize(self, campaign: CampaignModel, action_type: str, reason: str):
        """Log an AUTO_OPTIMIZE action to ActivityLogModel."""
        log = ActivityLogModel(
            action="AUTO_OPTIMIZE",
            entity_type="campaign",
            entity_id=str(campaign.id),
            details=f"[{action_type}] {reason}",
            timestamp=datetime.utcnow(),
        )
        self.db.add(log)

    def _optimize_campaign(self, campaign: CampaignModel) -> List[Dict]:
        actions = []

        if (campaign.impressions or 0) < self.MIN_IMPRESSIONS_FOR_DECISION:
            return [{
                "campaign_id": campaign.id,
                "action": "waiting",
                "reason": f"Insufficient data ({campaign.impressions} impressions, need {self.MIN_IMPRESSIONS_FOR_DECISION})",
            }]

        impressions = campaign.impressions or 0
        clicks = campaign.clicks or 0
        conversions = campaign.conversions or 0
        spend = campaign.total_spend or 0
        revenue = campaign.total_revenue or 0

        ctr = clicks / impressions if impressions > 0 else 0
        conversion_rate = conversions / clicks if clicks > 0 else 0
        roas = revenue / spend if spend > 0 else 0
        cpc = spend / clicks if clicks > 0 else 0

        # --- Actionable rule: pause_underperformer ---
        # ROAS < 0.5 after $20+ spend -> auto-pause
        if spend >= 20 and roas < 0.5:
            reason = f"ROAS {roas:.2f}x < 0.5 after ${spend:.2f} spend — auto-pausing"
            result = self._execute_meta_pause(campaign, reason)
            actions.append({
                "campaign_id": campaign.id,
                "action": "pause_underperformer",
                "reason": reason,
                "executed": result.get("executed", False),
            })
            campaign.updated_at = datetime.utcnow()
            return actions  # Paused — no further optimization needed

        # --- Actionable rule: flag_landing_page with CPC thresholds ---
        if clicks >= self.MIN_CLICKS_FOR_DECISION and ctr > self.HIGH_CTR_THRESHOLD and conversion_rate < self.LOW_CONVERSION_RATE:
            if cpc > 1.00:
                # CPC > $1.00: auto-pause
                reason = f"Landing page issue: CTR {ctr:.2%}, conv {conversion_rate:.2%}, CPC ${cpc:.2f} > $1.00 — auto-pausing"
                result = self._execute_meta_pause(campaign, reason)
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "flag_landing_page_pause",
                    "reason": reason,
                    "executed": result.get("executed", False),
                })
                campaign.updated_at = datetime.utcnow()
                return actions
            elif cpc > 0.50:
                # CPC > $0.50: auto-reduce budget by 25%
                new_budget = max((campaign.daily_budget or 10) * 0.75, self.MIN_DAILY_BUDGET)
                reason = f"Landing page issue: CTR {ctr:.2%}, conv {conversion_rate:.2%}, CPC ${cpc:.2f} > $0.50 — reducing budget 25%"
                result = self._execute_meta_budget_change(campaign, new_budget, reason)
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "flag_landing_page_budget_cut",
                    "reason": reason,
                    "executed": result.get("executed", False),
                })

        # --- Actionable rule: scale_winner ---
        # CTR > 3% AND CPC < $0.20 -> auto-increase budget by 20% (cap $25/day)
        if ctr > 0.03 and cpc < 0.20 and clicks >= self.MIN_CLICKS_FOR_DECISION:
            new_budget = min(
                (campaign.daily_budget or 10) * self.SCALE_WINNER_INCREASE,
                self.SCALE_WINNER_MAX_BUDGET,
            )
            if new_budget > (campaign.daily_budget or 0):
                reason = f"Scale winner: CTR {ctr:.2%}, CPC ${cpc:.2f} — increasing budget 20% (cap $25)"
                result = self._execute_meta_budget_change(campaign, new_budget, reason)
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "scale_winner",
                    "reason": reason,
                    "executed": result.get("executed", False),
                })

        # --- Existing ROAS-based budget adjustments ---
        if spend > 20:
            if roas >= self.settings["min_roas_threshold"] * 1.5:
                new_budget = min(
                    (campaign.daily_budget or 10) * self.BUDGET_INCREASE_FACTOR,
                    self.MAX_DAILY_BUDGET
                )
                if new_budget != campaign.daily_budget:
                    reason = f"Strong ROAS ({roas:.2f}x) — budget increase"
                    result = self._execute_meta_budget_change(campaign, new_budget, reason)
                    actions.append({
                        "campaign_id": campaign.id,
                        "action": "budget_increase",
                        "reason": reason,
                        "executed": result.get("executed", False),
                    })

            elif roas < self.settings["min_roas_threshold"] and spend > 50:
                new_budget = max(
                    (campaign.daily_budget or 10) * self.BUDGET_DECREASE_FACTOR,
                    self.MIN_DAILY_BUDGET
                )
                reason = f"Low ROAS ({roas:.2f}x < {self.settings['min_roas_threshold']}x) — budget decrease"
                result = self._execute_meta_budget_change(campaign, new_budget, reason)
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "budget_decrease",
                    "reason": reason,
                    "executed": result.get("executed", False),
                })

            elif roas < 0.5 and spend > 100:
                reason = f"Very low ROAS ({roas:.2f}x) after ${spend:.2f} spend — pausing"
                result = self._execute_meta_pause(campaign, reason)
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "paused",
                    "reason": reason,
                    "executed": result.get("executed", False),
                })

        # --- Flags (informational only, no API action) ---
        if clicks >= self.MIN_CLICKS_FOR_DECISION:
            if ctr < self.LOW_CTR_THRESHOLD:
                actions.append({
                    "campaign_id": campaign.id,
                    "action": "flag_low_ctr",
                    "reason": f"CTR {ctr:.3%} below threshold — consider ad copy refresh",
                    "suggestion": "refresh_ad_copy",
                })

        if clicks > 0 and cpc > (campaign.daily_budget or 10) * 0.5:
            actions.append({
                "campaign_id": campaign.id,
                "action": "flag_high_cpc",
                "reason": f"CPC (${cpc:.2f}) is >50% of daily budget — review keyword bids",
                "suggestion": "adjust_bids",
            })

        campaign.updated_at = datetime.utcnow()

        if not actions:
            actions.append({
                "campaign_id": campaign.id,
                "action": "no_change",
                "reason": f"Performance within targets (ROAS: {roas:.2f}x, CTR: {ctr:.2%})",
            })

        return actions

    def _check_safety_limits(self, campaigns: List[CampaignModel]) -> List[Dict]:
        actions = []

        total_daily_budget = sum(c.daily_budget or 0 for c in campaigns)
        total_spend = sum(c.total_spend or 0 for c in campaigns)
        total_revenue = sum(c.total_revenue or 0 for c in campaigns)

        if total_daily_budget > self.settings["daily_spend_limit"]:
            scale_factor = self.settings["daily_spend_limit"] / total_daily_budget
            for c in campaigns:
                if c.daily_budget:
                    c.daily_budget = round(c.daily_budget * scale_factor, 2)
            actions.append({
                "action": "global_budget_scale",
                "reason": f"Total daily budget ${total_daily_budget:.2f} exceeds limit ${self.settings['daily_spend_limit']:.2f}, scaled by {scale_factor:.2f}",
            })
            self._log_activity(f"Global budget scaled: {scale_factor:.2f}x to stay within ${self.settings['daily_spend_limit']} daily limit")

        net_loss = total_spend - total_revenue
        if net_loss > self.settings["emergency_pause_loss"]:
            for c in campaigns:
                c.status = "paused"
            actions.append({
                "action": "emergency_pause_all",
                "reason": f"Net loss ${net_loss:.2f} exceeds emergency threshold ${self.settings['emergency_pause_loss']:.2f}",
            })
            self._log_activity(f"EMERGENCY: All campaigns paused. Net loss ${net_loss:.2f}")

        return actions

    def get_optimization_summary(self) -> Dict:
        campaigns = self.db.query(CampaignModel).all()

        total_spend = sum(c.total_spend or 0 for c in campaigns)
        total_revenue = sum(c.total_revenue or 0 for c in campaigns)
        total_impressions = sum(c.impressions or 0 for c in campaigns)
        total_clicks = sum(c.clicks or 0 for c in campaigns)
        total_conversions = sum(c.conversions or 0 for c in campaigns)

        active = [c for c in campaigns if c.status in ("active", "live")]
        paused = [c for c in campaigns if c.status == "paused"]
        drafts = [c for c in campaigns if c.status == "draft"]

        return {
            "total_campaigns": len(campaigns),
            "active": len(active),
            "paused": len(paused),
            "drafts": len(drafts),
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "overall_roas": round(total_revenue / total_spend, 2) if total_spend > 0 else 0,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "avg_ctr": round(total_clicks / total_impressions, 4) if total_impressions > 0 else 0,
            "avg_conversion_rate": round(total_conversions / total_clicks, 4) if total_clicks > 0 else 0,
            "daily_budget_utilization": round(
                sum(c.daily_budget or 0 for c in active) / self.settings["daily_spend_limit"] * 100, 1
            ) if self.settings["daily_spend_limit"] > 0 else 0,
        }

    def _log_activity(self, message: str):
        log = ActivityLogModel(
            action="optimization",
            details=message,
            timestamp=datetime.utcnow(),
        )
        self.db.add(log)
