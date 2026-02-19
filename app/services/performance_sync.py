"""
Performance Sync Service
Pulls live performance data from Meta and TikTok, writes to CampaignModel records.
Auto-discovers real platform campaigns that have no local CampaignModel record.
"""

import logging
from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from app.database import CampaignModel, ActivityLogModel
from app.services.meta_ads import MetaAdsService
from app.services.google_ads import GoogleAdsService

logger = logging.getLogger("autosem.performance_sync")

# Known real Meta campaigns
KNOWN_META_CAMPAIGNS = [
    {"id": "120241759616260364", "name": "Sales Campaign", "default_status": "PAUSED"},
    {"id": "120206746647300364", "name": "Ongoing Campaign", "default_status": "ACTIVE"},
]


class PerformanceSyncService:
    """Syncs performance data from ad platforms into local CampaignModel records."""

    def __init__(self, db: Session):
        self.db = db
        self.meta = MetaAdsService()
        self.google = GoogleAdsService()

    def sync_all(self) -> Dict:
        """Run a full performance sync across all platforms."""
        results = {
            "meta": {"synced": 0, "discovered": 0, "errors": []},
            "google": {"synced": 0, "cleaned": 0, "errors": []},
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Clean phantom Google Ads campaigns (null platform_campaign_id)
        cleaned = self._clean_phantom_google_campaigns()
        results["google"]["cleaned"] = cleaned

        # Ensure known Meta campaigns exist locally
        discovered = self._discover_meta_campaigns()
        results["meta"]["discovered"] = discovered

        # Sync Meta performance
        try:
            meta_synced = self._sync_meta_performance()
            results["meta"]["synced"] = meta_synced
        except Exception as e:
            logger.error(f"Meta performance sync failed: {e}")
            results["meta"]["errors"].append(str(e))

        # Sync Google performance
        try:
            google_synced = self._sync_google_performance()
            results["google"]["synced"] = google_synced
        except Exception as e:
            logger.error(f"Google performance sync failed: {e}")
            results["google"]["errors"].append(str(e))

        self._log_activity(
            "PERFORMANCE_SYNC",
            details=f"Synced: Meta {results['meta']['synced']}, Google {results['google']['synced']}, "
                    f"Discovered: {discovered}",
        )

        return results

    def _discover_meta_campaigns(self) -> int:
        """Ensure known real Meta campaigns have local CampaignModel records."""
        discovered = 0
        for known in KNOWN_META_CAMPAIGNS:
            existing = self.db.query(CampaignModel).filter(
                CampaignModel.platform == "meta",
                CampaignModel.platform_campaign_id == known["id"],
            ).first()

            if not existing:
                campaign = CampaignModel(
                    platform="meta",
                    platform_campaign_id=known["id"],
                    name=known["name"],
                    status=known["default_status"].lower(),
                    daily_budget=0.0,
                    spend=0.0,
                    revenue=0.0,
                    total_spend=0.0,
                    total_revenue=0.0,
                    conversions=0,
                    roas=0.0,
                )
                self.db.add(campaign)
                discovered += 1
                logger.info(f"Discovered Meta campaign: {known['name']} ({known['id']})")

        if discovered:
            self.db.commit()

        return discovered

    def _sync_meta_performance(self) -> int:
        """Pull live performance data from Meta and update local records."""
        if not self.meta.is_configured:
            logger.info("Meta not configured - skipping performance sync")
            return 0

        performance_data = self.meta.get_performance(days=7)
        if not performance_data:
            return 0

        synced = 0
        for row in performance_data:
            campaign_id = row.get("campaign_id")
            if not campaign_id:
                continue

            campaign = self.db.query(CampaignModel).filter(
                CampaignModel.platform == "meta",
                CampaignModel.platform_campaign_id == campaign_id,
            ).first()

            if not campaign:
                # Auto-discover unknown campaign
                campaign = CampaignModel(
                    platform="meta",
                    platform_campaign_id=campaign_id,
                    name=row.get("campaign_name", f"Meta Campaign {campaign_id}"),
                    status="active",
                    daily_budget=0.0,
                    spend=0.0,
                    revenue=0.0,
                    total_spend=0.0,
                    total_revenue=0.0,
                    conversions=0,
                    roas=0.0,
                )
                self.db.add(campaign)
                self.db.flush()
                logger.info(f"Auto-discovered Meta campaign: {campaign_id}")

            # Update performance fields
            campaign.spend = float(row.get("spend", 0))
            campaign.total_spend = float(row.get("spend", 0))
            campaign.revenue = float(row.get("revenue", 0))
            campaign.total_revenue = float(row.get("revenue", 0))
            campaign.conversions = int(row.get("conversions", 0))
            campaign.roas = (campaign.revenue / campaign.spend) if campaign.spend > 0 else 0.0
            campaign.updated_at = datetime.utcnow()
            synced += 1

        self.db.commit()
        logger.info(f"Meta performance sync: {synced} campaigns updated")
        return synced

    def _sync_google_performance(self) -> int:
        """Pull live performance data from Google Ads and update local records."""
        if not self.google.is_configured:
            logger.info("Google Ads not configured - skipping performance sync")
            return 0

        performance_data = self.google.get_performance(days=7)
        if not performance_data:
            return 0

        synced = 0
        for row in performance_data:
            campaign_id = row.get("campaign_id")
            if not campaign_id:
                continue

            campaign = self.db.query(CampaignModel).filter(
                CampaignModel.platform == "google_ads",
                CampaignModel.platform_campaign_id == campaign_id,
            ).first()

            if not campaign:
                continue

            campaign.spend = float(row.get("spend", 0))
            campaign.total_spend = float(row.get("spend", 0))
            campaign.revenue = float(row.get("revenue", 0))
            campaign.total_revenue = float(row.get("revenue", 0))
            campaign.conversions = int(row.get("conversions", 0))
            campaign.roas = (campaign.revenue / campaign.spend) if campaign.spend > 0 else 0.0
            campaign.updated_at = datetime.utcnow()
            synced += 1

        self.db.commit()
        logger.info(f"Google performance sync: {synced} campaigns updated")
        return synced

    def _clean_phantom_google_campaigns(self) -> int:
        """Mark phantom Google Ads campaigns (no platform_campaign_id) as draft."""
        phantoms = self.db.query(CampaignModel).filter(
            CampaignModel.platform == "google_ads",
            CampaignModel.platform_campaign_id == None,
            CampaignModel.status != "draft",
        ).all()

        if not phantoms:
            return 0

        for campaign in phantoms:
            campaign.status = "draft"
            campaign.updated_at = datetime.utcnow()

        self.db.commit()
        logger.info(f"Cleaned {len(phantoms)} phantom Google Ads campaigns -> draft")
        return len(phantoms)

    def _log_activity(self, action: str, entity_id: str = "", details: str = ""):
        try:
            log = ActivityLogModel(
                action=action,
                entity_type="performance_sync",
                entity_id=entity_id,
                details=details,
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log activity: {e}")
