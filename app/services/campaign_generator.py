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

    def __init__(self, db: Session):
        self.db = db
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

    def generate_campaigns(self, platform: str = "both") -> List[Dict]:
        products = self.db.query(ProductModel).filter(
            ProductModel.status == "active"
        ).all()

        if not products:
            logger.warning("No active products found for campaign generation")
            return []

        existing_campaigns = self.db.query(CampaignModel).all()
        existing_product_platforms = {
            (c.product_id, c.platform) for c in existing_campaigns
        }

        platforms = []
        if platform in ("google", "both"):
            platforms.append("google")
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

        logger.info(f"Generated {len(created)} new campaigns")
        return created

    def _create_campaign_for_product(self, product: ProductModel, platform: str) -> Optional[Dict]:
        product_price = product.price or 0
        if product_price <= 0:
            logger.warning(f"Skipping product {product.id} - no price set")
            return None

        estimated_margin = product_price * 0.45
        daily_budget = round(estimated_margin / self.settings["min_roas_threshold"], 2)
        daily_budget = min(daily_budget, 25.0)
        daily_budget = max(daily_budget, 5.0)

        title_short = (product.title or "Product")[:50]
        campaign_name = f"AutoSEM - {title_short} - {platform.title()}"

        ad_copy = self._generate_ad_copy(product, platform)
        keywords = self._generate_keywords(product) if platform == "google" else []
        targeting = self._generate_targeting(product, platform)

        campaign = CampaignModel(
            product_id=product.id,
            platform=platform,
            campaign_name=campaign_name,
            status="draft",
            daily_budget=daily_budget,
            total_spend=0.0,
            total_revenue=0.0,
            roas=0.0,
            impressions=0,
            clicks=0,
            conversions=0,
            ad_copy=ad_copy.get("headline", ""),
            keywords=", ".join(keywords) if keywords else None,
            targeting=str(targeting),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        self.db.add(campaign)
        self.db.commit()
        self.db.refresh(campaign)

        result = {
            "id": campaign.id,
            "product_id": product.id,
            "product_title": product.title,
            "platform": platform,
            "campaign_name": campaign_name,
            "daily_budget": daily_budget,
            "status": "draft",
            "ad_copy": ad_copy,
            "keywords": keywords,
            "targeting": targeting,
        }

        logger.info(f"Created campaign: {campaign_name}")
        return result

    def _generate_ad_copy(self, product: ProductModel, platform: str) -> Dict:
        title = product.title or "Tennis Apparel"
        
        is_hat = any(w in title.lower() for w in ["hat", "cap", "visor"])
        is_shirt = any(w in title.lower() for w in ["shirt", "tee", "polo", "top"])
        is_shorts = any(w in title.lower() for w in ["shorts", "skirt", "skort"])

        if is_hat:
            category = "headwear"
            benefit = "Stay cool on the court"
        elif is_shirt:
            category = "apparel"
            benefit = "Look sharp, play sharper"
        elif is_shorts:
            category = "bottoms"
            benefit = "Move freely on every shot"
        else:
            category = "gear"
            benefit = "Elevate your tennis game"

        price_text = f"${product.price:.0f}" if product.price else ""

        if platform == "google":
            return {
                "headline": f"{title} | Court Sportswear",
                "headline_2": benefit,
                "headline_3": f"Premium Tennis {category.title()}",
                "description": f"Shop {title} from Court Sportswear. {benefit}. Free shipping on orders $50+. {price_text}",
                "description_2": f"Premium tennis {category} designed for players who demand style and performance. Shop now at Court Sportswear.",
                "display_url": "court-sportswear.com",
                "final_url": product.url or "https://court-sportswear.com",
            }
        else:
            return {
                "headline": f"{title}",
                "primary_text": f"{benefit} with {title} from Court Sportswear. Premium tennis {category} for players who demand the best. 🎾",
                "description": f"Shop now - {price_text}" if price_text else "Shop the collection",
                "cta": "SHOP_NOW",
                "link": product.url or "https://court-sportswear.com",
            }

    def _generate_keywords(self, product: ProductModel) -> List[str]:
        title = (product.title or "").lower()
        keywords = []

        if any(w in title for w in ["hat", "cap", "visor"]):
            keywords.extend([
                "tennis hat", "tennis cap", "tennis visor",
                "tennis headwear", "court hat", "tennis sun hat",
            ])
        elif any(w in title for w in ["shirt", "tee", "polo", "top"]):
            keywords.extend([
                "tennis shirt", "tennis polo", "tennis top",
                "tennis tee", "court shirt", "tennis apparel",
            ])
        elif any(w in title for w in ["shorts", "skirt", "skort"]):
            keywords.extend([
                "tennis shorts", "tennis skirt", "tennis skort",
                "court shorts", "tennis bottoms",
            ])
        else:
            keywords.extend([
                "tennis gear", "tennis accessories",
                "court sportswear", "tennis outfit",
            ])

        keywords.extend(["court sportswear", "court tennis"])

        title_words = [w for w in title.split() if len(w) > 3 and w not in ("with", "from", "this", "that")]
        for word in title_words[:5]:
            keywords.append(f"tennis {word}")

        return list(set(keywords))

    def _generate_targeting(self, product: ProductModel, platform: str) -> Dict:
        base_targeting = {
            "age_range": "25-55",
            "gender": "all",
            "countries": ["US"],
            "interests": ["tennis", "racquet sports", "athletic apparel", "sports fashion"],
        }

        if platform == "google":
            base_targeting.update({
                "match_type": "phrase",
                "network": "search",
                "bid_strategy": "target_roas",
                "target_roas": self.settings["min_roas_threshold"],
            })
        else:
            base_targeting.update({
                "placements": ["facebook_feed", "instagram_feed", "instagram_stories"],
                "optimization_goal": "CONVERSIONS",
                "pixel_event": "Purchase",
                "lookalike_source": "website_visitors",
            })

        return base_targeting
