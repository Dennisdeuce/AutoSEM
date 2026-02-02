from typing import Dict, Any
from app.models import Product


class BiddingEngine:
    def calculate_target_cpa(self, product: Product) -> float:
        """
        Target CPA = Maximum we can pay for a conversion while staying profitable
        """
        selling_price = product.price or 0
        cogs = product.cost_price or 0  # Product + shipping from Printful

        if selling_price == 0:
            return 5.00  # Floor

        gross_margin = selling_price - cogs

        # Reserve margin for operations (30% of gross)
        reserved_margin = gross_margin * 0.30

        # Maximum allowable ad spend per sale
        max_cpa = gross_margin - reserved_margin

        # Apply safety buffer (target 80% of max)
        target_cpa = max_cpa * 0.80

        return max(target_cpa, 5.00)  # Floor of $5 CPA minimum

    def calculate_target_roas(self, product: Product) -> float:
        """
        Minimum ROAS = Revenue / Max Ad Spend
        """
        cogs = product.cost_price or 0
        min_margin_percent = 0.25  # Want at least 25% net margin

        if product.price and product.price > 0:
            max_ad_spend_ratio = 1 - (cogs / product.price) - min_margin_percent
            target_roas = 1 / max_ad_spend_ratio
            return max(target_roas, 2.5)  # Floor of 2.5x ROAS

        return 2.5

    def calculate_optimal_bid(self, product: Product, current_performance: Dict[str, Any] = None) -> float:
        """
        Calculate optimal bid based on target CPA and current performance
        """
        target_cpa = self.calculate_target_cpa(product)

        if current_performance:
            # Adjust based on performance
            current_roas = current_performance.get("roas", 0)
            target_roas = self.calculate_target_roas(product)

            if current_roas > target_roas * 1.2:  # Performing well
                return target_cpa * 1.1  # Increase bid
            elif current_roas < target_roas * 0.8:  # Underperforming
                return target_cpa * 0.9  # Decrease bid

        return target_cpa


class BudgetAllocator:
    def allocate_daily_budget(self, total_daily_budget: float, campaigns: list) -> Dict[int, float]:
        """
        Dynamically allocate budget based on performance
        """
        allocations = {}

        if not campaigns:
            return allocations

        for campaign in campaigns:
            # Score based on ROAS, volume, and trend
            roas_score = getattr(campaign, 'roas', 0) / getattr(campaign, 'target_roas', 1)
            volume_score = getattr(campaign, 'conversions', 0) / max(1, max(getattr(c, 'conversions', 0) for c in campaigns))
            trend_score = 1.0  # Placeholder for trend calculation

            composite_score = (roas_score * 0.5) + (volume_score * 0.3) + (trend_score * 0.2)
            allocations[campaign.id] = composite_score

        # Normalize and apply
        total_score = sum(allocations.values())
        if total_score > 0:
            for campaign_id, score in allocations.items():
                allocations[campaign_id] = (score / total_score) * total_daily_budget

        # Ensure minimums for learning campaigns
        for campaign_id in allocations:
            allocations[campaign_id] = max(allocations[campaign_id], 10.00)

        return allocations


bidding_engine = BiddingEngine()
budget_allocator = BudgetAllocator()