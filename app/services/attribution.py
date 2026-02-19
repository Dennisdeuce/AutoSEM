"""
UTM-Based Revenue Attribution Service
Parses Shopify order data to attribute revenue to ad campaigns.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

from sqlalchemy.orm import Session

from app.database import CampaignModel, ActivityLogModel

logger = logging.getLogger("autosem.attribution")

# Maps UTM source values to platform identifiers
PLATFORM_MAP = {
    "meta": "meta",
    "facebook": "meta",
    "fb": "meta",
    "instagram": "meta",
    "ig": "meta",
    "google": "google_ads",
    "gads": "google_ads",
    "tiktok": "tiktok",
    "klaviyo": "klaviyo",
    "email": "klaviyo",
}


class AttributionService:
    """Attributes Shopify order revenue to the correct ad campaign."""

    def __init__(self, db: Session):
        self.db = db

    def attribute_order(self, order: Dict) -> Dict:
        """Parse a Shopify order and attribute revenue to a campaign.

        Returns an attribution result dict with order_id, total_price,
        utm params, matched campaign info, and whether attribution succeeded.
        """
        order_id = order.get("id", "unknown")
        total_price = float(order.get("total_price", 0))

        # Extract UTM params
        utm = self._extract_utm(order)

        # Determine ad platform
        platform = self._resolve_platform(utm["utm_source"])

        # Match to a campaign
        campaign = self._match_campaign(utm["utm_campaign"], utm["utm_source"], platform)

        result = {
            "order_id": order_id,
            "total_price": total_price,
            "utm_source": utm["utm_source"],
            "utm_medium": utm["utm_medium"],
            "utm_campaign": utm["utm_campaign"],
            "utm_content": utm["utm_content"],
            "platform": platform,
            "campaign_id": None,
            "campaign_name": None,
            "attributed": False,
        }

        if campaign and total_price > 0:
            campaign.total_revenue = (campaign.total_revenue or 0) + total_price
            campaign.revenue = (campaign.revenue or 0) + total_price
            campaign.conversions = (campaign.conversions or 0) + 1
            if campaign.total_spend and campaign.total_spend > 0:
                campaign.roas = campaign.total_revenue / campaign.total_spend
            campaign.updated_at = datetime.now(timezone.utc)
            self.db.commit()

            result["campaign_id"] = campaign.id
            result["campaign_name"] = campaign.name
            result["attributed"] = True

            self._log(
                "ORDER_ATTRIBUTED", str(order_id),
                f"${total_price:.2f} -> '{campaign.name}' "
                f"(utm_source={utm['utm_source']}, platform={platform})",
            )
        else:
            self._log(
                "ORDER_UNATTRIBUTED", str(order_id),
                f"${total_price:.2f} unattributed "
                f"(utm_source={utm['utm_source']}, utm_campaign={utm['utm_campaign']})",
            )

        return result

    def _extract_utm(self, order: Dict) -> Dict:
        """Extract UTM parameters from landing_site, referring_site, and note_attributes."""
        utm = {
            "utm_source": "",
            "utm_medium": "",
            "utm_campaign": "",
            "utm_content": "",
        }

        # Parse from landing_site or referring_site URLs
        for url_field in ("landing_site", "referring_site"):
            source_url = order.get(url_field, "") or ""
            if "?" in source_url:
                parsed = urlparse(source_url)
                params = parse_qs(parsed.query)
                for key in utm:
                    if not utm[key]:
                        utm[key] = params.get(key, [""])[0]

        # Also check note_attributes (Shopify custom attributes on checkout)
        for attr in order.get("note_attributes", []):
            name = attr.get("name", "")
            value = attr.get("value", "")
            if name in utm and not utm[name]:
                utm[name] = value

        return utm

    def _resolve_platform(self, utm_source: str) -> Optional[str]:
        """Map utm_source to an ad platform identifier."""
        if not utm_source:
            return None
        source_lower = utm_source.lower()
        for keyword, platform in PLATFORM_MAP.items():
            if keyword in source_lower:
                return platform
        return None

    def _match_campaign(self, utm_campaign: str, utm_source: str,
                        platform: Optional[str]) -> Optional[CampaignModel]:
        """Try to match to a CampaignModel, from most to least specific."""

        # 1. Exact match on platform_campaign_id
        if utm_campaign:
            campaign = self.db.query(CampaignModel).filter(
                CampaignModel.platform_campaign_id == utm_campaign,
            ).first()
            if campaign:
                return campaign

            # 2. Fuzzy match on campaign name
            campaign = self.db.query(CampaignModel).filter(
                CampaignModel.name.ilike(f"%{utm_campaign}%"),
            ).first()
            if campaign:
                return campaign

        # 3. Fallback: most recently active campaign on the matched platform
        if platform:
            campaign = self.db.query(CampaignModel).filter(
                CampaignModel.platform == platform,
                CampaignModel.status.in_(["active", "ACTIVE", "live"]),
            ).order_by(CampaignModel.updated_at.desc()).first()
            if campaign:
                return campaign

        return None

    def _log(self, action: str, entity_id: str, details: str):
        try:
            log = ActivityLogModel(
                action=action,
                entity_type="attribution",
                entity_id=entity_id,
                details=details,
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log attribution: {e}")
