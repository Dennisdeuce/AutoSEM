"""
Campaign Generator Service
Automatically creates Google Ads and Meta campaigns from Shopify products.
"""
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.database import ProductModel, CampaignModel, SettingsModel

logger = logging.getLogger("autosem.campaign_generator")


class CampaignGenerator:
    """Generates ad campaigns from product catalog."""

    def __init__(self, db: Session = None):
        self.db = db

    def create_for_uncovered_products(self, db: Session) -> int:
        """Create campaigns for products that don't have any yet."""
        self.db = db
        products = db.query(ProductModel).filter(ProductModel.is_available == True).all()
        existing = {c.product_id for c in db.query(CampaignModel).all()}
        created = 0
        for p in products:
            if p.id not in existing:
                campaign = self._create_campaign_for_product(p, "google_ads")
                if campaign:
                    created += 1
        return created

    def generate_campaigns(self, platform: str = "both") -> List[Dict]:
        products = self.db.query(ProductModel).filter(ProductModel.is_available == True).all()
        if not products:
            return []
        existing_campaigns = self.db.query(CampaignModel).all()
        existing_product_platforms = {(c.product_id, c.platform) for c in existing_campaigns}
        platforms = []
        if platform in ("google", "both", "google_ads"):
            platforms.append("google_ads")
        if platform in ("meta", "both"):
            platforms.append("meta")
        created = []
        for product in products:
            for plat in platforms:
                if (product.id, plat) in existing_product_platforms:
                    continue
                campaign = self._create_campaign_for_product(product, plat)
                if campaign:
                    created.append(campaign)
        return created

    def _create_campaign_for_product(self, product: ProductModel, platform: str) -> Optional[Dict]:
        product_price = product.price or 0
        if product_price <= 0:
            return None

        estimated_margin = product_price * 0.45
        daily_budget = round(estimated_margin / 1.5, 2)
        daily_budget = min(daily_budget, 25.0)
        daily_budget = max(daily_budget, 5.0)

        title_short = (product.title or "Product")[:50]
        campaign_name = f"AutoSEM - {title_short} - {platform.title()}"
        ad_copy = self._generate_ad_copy(product, platform)
        keywords = self._generate_keywords(product) if "google" in platform else []

        campaign = CampaignModel(
            product_id=product.id,
            platform=platform,
            name=campaign_name,
            status="active",
            daily_budget=daily_budget,
            spend=0.0,
            revenue=0.0,
            total_spend=0.0,
            total_revenue=0.0,
            roas=0.0,
            conversions=0,
            headlines=ad_copy.get("headline", ""),
            descriptions=ad_copy.get("description", ""),
            keywords=", ".join(keywords) if keywords else None,
        )

        self.db.add(campaign)
        self.db.commit()
        self.db.refresh(campaign)

        return {
            "id": campaign.id,
            "product_id": product.id,
            "product_title": product.title,
            "platform": platform,
            "campaign_name": campaign_name,
            "daily_budget": daily_budget,
        }

    def _generate_ad_copy(self, product: ProductModel, platform: str) -> Dict:
        title = product.title or "Tennis Apparel"
        is_hat = any(w in title.lower() for w in ["hat", "cap", "visor"])
        is_shirt = any(w in title.lower() for w in ["shirt", "tee", "polo", "top"])
        is_shorts = any(w in title.lower() for w in ["shorts", "skirt", "skort"])

        if is_hat:
            category, benefit = "headwear", "Stay cool on the court"
        elif is_shirt:
            category, benefit = "apparel", "Look sharp, play sharper"
        elif is_shorts:
            category, benefit = "bottoms", "Move freely on every shot"
        else:
            category, benefit = "gear", "Elevate your tennis game"

        price_text = f"${product.price:.0f}" if product.price else ""

        if "google" in platform:
            return {
                "headline": f"{title} | Court Sportswear",
                "headline_2": benefit,
                "headline_3": f"Premium Tennis {category.title()}",
                "description": f"Shop {title} from Court Sportswear. {benefit}. Free shipping on orders $50+. {price_text}",
                "description_2": f"Premium tennis {category} designed for players who demand style and performance.",
            }
        else:
            return {
                "headline": title,
                "description": f"{benefit} with {title} from Court Sportswear. Premium tennis {category} for players who demand the best.",
                "cta": "SHOP_NOW",
            }

    def _generate_keywords(self, product: ProductModel) -> List[str]:
        title = (product.title or "").lower()
        keywords = []
        if any(w in title for w in ["hat", "cap", "visor"]):
            keywords.extend(["tennis hat", "tennis cap", "tennis visor", "tennis headwear", "court hat"])
        elif any(w in title for w in ["shirt", "tee", "polo", "top"]):
            keywords.extend(["tennis shirt", "tennis polo", "tennis top", "tennis tee", "court shirt"])
        elif any(w in title for w in ["shorts", "skirt", "skort"]):
            keywords.extend(["tennis shorts", "tennis skirt", "tennis skort", "court shorts"])
        else:
            keywords.extend(["tennis gear", "tennis accessories", "court sportswear", "tennis outfit"])
        keywords.extend(["court sportswear", "court tennis"])
        title_words = [w for w in title.split() if len(w) > 3 and w not in ("with", "from", "this", "that")]
        for word in title_words[:5]:
            keywords.append(f"tennis {word}")
        return list(set(keywords))

    def _generate_targeting(self, product: ProductModel, platform: str) -> Dict:
        base = {
            "age_range": "25-55", "gender": "all", "countries": ["US"],
            "interests": ["tennis", "racquet sports", "athletic apparel"],
        }
        if "google" in platform:
            base.update({"match_type": "phrase", "network": "search", "bid_strategy": "target_roas", "target_roas": 1.5})
        else:
            base.update({"placements": ["facebook_feed", "instagram_feed"], "optimization_goal": "CONVERSIONS"})
        return base
