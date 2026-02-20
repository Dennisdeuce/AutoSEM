"""Performance Sync Service
Pulls live campaign data from Meta and TikTok, updates local CampaignModel records.
Discovers unlinked real campaigns and creates local records for them.

v2.0 - Phase 10: Load Meta token from DB, write all metrics (reach, CTR, CPC)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List
from sqlalchemy.orm import Session

from app.database import CampaignModel, ActivityLogModel, MetaTokenModel
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
        # Load token from DB if env var is empty (token is usually in meta_tokens table)
        self._load_db_token()

    def _load_db_token(self):
        """Load Meta token from DB if the env var is empty or stale."""
        try:
            if not self.meta.access_token:
                token_record = self.db.query(MetaTokenModel).first()
                if token_record and token_record.access_token:
                    self.meta.update_token(token_record.access_token)
                    logger.info("PerformanceSyncService: loaded Meta token from DB")
        except Exception as e:
            logger.warning(f"Failed to load Meta token from DB: {e}")

    def sync_all(self) -> Dict:
        """Run full sync across all platforms."""
        # Re-check token before sync (may have been refreshed since init)
        self._load_db_token()

        results = {
            "meta": self._sync_meta(),
            "discovered": self._discover_unlinked_campaigns(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._log_activity(
            f"Sync: meta={results['meta'].get('status', 'unknown')}, "
            f"synced={results['meta'].get('campaigns_synced', 0)}, "
            f"discovered={results['discovered'].get('new_campaigns_linked', 0)}"
        )
        return results

    def _sync_meta(self) -> Dict:
        """Pull Meta campaign performance and update local CampaignModel records.

        Writes: impressions, clicks, spend, total_spend, conversions, revenue,
        total_revenue, roas, status. Calculates CTR/CPC for logging.
        """
        if not self.meta.is_configured:
            return {"status": "skipped", "reason": "Meta not configured"}

        try:
            performance_data = self.meta.get_performance(days=7)
            if not performance_data:
                return {"status": "ok", "campaigns_synced": 0, "message": "No performance data returned"}

            synced = 0
            details = []
            for row in performance_data:
                meta_campaign_id = row.get("campaign_id")
                if not meta_campaign_id:
                    continue

                # Find matching local campaign
                campaign = self.db.query(CampaignModel).filter(
                    CampaignModel.platform_campaign_id == str(meta_campaign_id),
                    CampaignModel.platform == "meta",
                ).first()

                spend = float(row.get("spend", 0))
                impressions = int(row.get("impressions", 0))
                clicks = int(row.get("clicks", 0))
                conversions = int(row.get("conversions", 0))
                revenue = float(row.get("revenue", 0))

                # Calculated metrics for logging
                ctr = (clicks / impressions * 100) if impressions > 0 else 0
                cpc = (spend / clicks) if clicks > 0 else 0
                roas = (revenue / spend) if spend > 0 else 0

                if campaign:
                    # Write ALL metrics back to the campaign row
                    campaign.impressions = impressions
                    campaign.clicks = clicks
                    campaign.spend = spend
                    campaign.total_spend = spend
                    campaign.conversions = conversions
                    campaign.revenue = revenue
                    campaign.total_revenue = revenue
                    campaign.roas = round(roas, 2)
                    # Normalize status to lowercase for consistent optimizer matching
                    meta_status = row.get("campaign_status", "").lower()
                    if meta_status in ("active", "paused", "deleted", "archived"):
                        campaign.status = meta_status
                    elif campaign.status and campaign.status.upper() == campaign.status:
                        # Fix any existing UPPERCASE status to lowercase
                        campaign.status = campaign.status.lower()
                    # Sync daily_budget from Meta (returned in cents)
                    raw_budget = row.get("daily_budget", 0)
                    if raw_budget:
                        campaign.daily_budget = float(raw_budget) / 100
                    campaign.updated_at = datetime.now(timezone.utc)
                    logger.info(f"Wrote to campaign {campaign.id}: impr={impressions}, "
                                f"clicks={clicks}, spend=${spend:.2f}, status={campaign.status}")
                    synced += 1
                    details.append(
                        f"{campaign.name[:30]}: ${spend:.2f} spend, {clicks} clicks, "
                        f"CTR={ctr:.1f}%, CPC=${cpc:.2f}, ROAS={roas:.1f}x"
                    )
                    logger.info(f"Synced {meta_campaign_id}: ${spend:.2f}, {clicks} clicks, "
                                f"CTR={ctr:.1f}%, CPC=${cpc:.2f}")
                else:
                    # Campaign exists on Meta but not locally — create it
                    self._create_local_campaign(
                        platform="meta",
                        platform_campaign_id=str(meta_campaign_id),
                        name=row.get("campaign_name", f"Meta Campaign {meta_campaign_id}"),
                        data=row,
                    )
                    synced += 1

            self.db.commit()
            return {
                "status": "ok",
                "campaigns_synced": synced,
                "details": details,
            }

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
