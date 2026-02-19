"""Performance Sync Service
Pulls live campaign data from Meta and TikTok, updates local CampaignModel records.
Discovers unlinked real campaigns and creates local records for them.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List
from sqlalchemy.orm import Session

from app.database import CampaignModel, ActivityLogModel
from app.services.meta_ads import MetaAdsService

logger = logging.getLogger("autosem.performance_sync")

# Known real Meta campaigns that must be tracked
KNOWN_META_CAMPAIGNS = [
    {"platform_campaign_id": "120241759616260364", "name": "Sales - Tennis Apparel"},
    {"platform_campaign_id": "120206746647300364", "name": "Ongoing - Tennis Apparel"},
]


class PerformanceSyncService:
    """Syncs performance data from ad platforms to local database."""

    def __init__(self, db: Session):
        self.db = db
        self.meta = MetaAdsService()

    def sync_all(self) -> Dict:
        """Run full sync across all platforms."""
        results = {
            "meta": self._sync_meta(),
            "discovered": self._discover_unlinked_campaigns(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._log_activity(f"Performance sync completed: {results}")
        return results

    def _sync_meta(self) -> Dict:
        """Pull Meta campaign performance and update local records.
        Wrapped with retry logic via the retry decorator on MetaAdsService methods.
        """
        if not self.meta.is_configured:
            return {"status": "skipped", "reason": "Meta not configured"}

        try:
            performance_data = self.meta.get_performance(days=7)
            if not performance_data:
                return {"status": "ok", "campaigns_synced": 0, "message": "No performance data returned"}

            synced = 0
            for row in performance_data:
                meta_campaign_id = row.get("campaign_id")
                if not meta_campaign_id:
                    continue

                # Find matching local campaign
                campaign = self.db.query(CampaignModel).filter(
                    CampaignModel.platform_campaign_id == str(meta_campaign_id),
                    CampaignModel.platform == "meta",
                ).first()

                if campaign:
                    campaign.impressions = row.get("impressions", 0)
                    campaign.clicks = row.get("clicks", 0)
                    campaign.total_spend = row.get("spend", 0)
                    campaign.spend = row.get("spend", 0)
                    campaign.conversions = row.get("conversions", 0)
                    campaign.total_revenue = row.get("revenue", 0)
                    campaign.revenue = row.get("revenue", 0)
                    if campaign.total_spend and campaign.total_spend > 0:
                        campaign.roas = campaign.total_revenue / campaign.total_spend
                    campaign.updated_at = datetime.now(timezone.utc)
                    synced += 1
                    logger.info(f"Synced Meta campaign {meta_campaign_id}: "
                                f"spend=${row.get('spend', 0):.2f}, clicks={row.get('clicks', 0)}")
                else:
                    # Campaign exists on Meta but not locally - create it
                    self._create_local_campaign(
                        platform="meta",
                        platform_campaign_id=str(meta_campaign_id),
                        name=row.get("campaign_name", f"Meta Campaign {meta_campaign_id}"),
                        data=row,
                    )
                    synced += 1

            self.db.commit()
            return {"status": "ok", "campaigns_synced": synced}

        except Exception as e:
            logger.error(f"Meta sync failed: {e}")
            return {"status": "error", "message": str(e)}

    def _discover_unlinked_campaigns(self) -> Dict:
        """Ensure known real campaigns have local CampaignModel records."""
        discovered = 0

        for known in KNOWN_META_CAMPAIGNS:
            existing = self.db.query(CampaignModel).filter(
                CampaignModel.platform_campaign_id == known["platform_campaign_id"],
                CampaignModel.platform == "meta",
            ).first()

            if not existing:
                campaign = CampaignModel(
                    name=known["name"],
                    platform="meta",
                    platform_campaign_id=known["platform_campaign_id"],
                    status="active",
                    daily_budget=10.0,
                    total_spend=0,
                    total_revenue=0,
                    impressions=0,
                    clicks=0,
                    conversions=0,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                self.db.add(campaign)
                discovered += 1
                logger.info(f"Discovered unlinked Meta campaign: {known['name']} ({known['platform_campaign_id']})")

        if discovered > 0:
            self.db.commit()

        return {"new_campaigns_linked": discovered}

    def _create_local_campaign(self, platform: str, platform_campaign_id: str,
                                name: str, data: Dict):
        """Create a local CampaignModel record for a discovered platform campaign."""
        campaign = CampaignModel(
            name=name,
            platform=platform,
            platform_campaign_id=platform_campaign_id,
            status="active",
            daily_budget=10.0,
            total_spend=data.get("spend", 0),
            total_revenue=data.get("revenue", 0),
            impressions=data.get("impressions", 0),
            clicks=data.get("clicks", 0),
            conversions=data.get("conversions", 0),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        if campaign.total_spend and campaign.total_spend > 0:
            campaign.roas = campaign.total_revenue / campaign.total_spend
        self.db.add(campaign)
        logger.info(f"Created local record for {platform} campaign: {name} ({platform_campaign_id})")

    def _log_activity(self, message: str):
        try:
            log = ActivityLogModel(
                action="PERFORMANCE_SYNC",
                details=message[:500],
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log sync activity: {e}")
