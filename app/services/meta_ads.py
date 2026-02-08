"""
Meta Ads Service
Manages Meta (Facebook/Instagram) ad campaigns and performance syncing.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger("autosem.meta_ads")


class MetaAdsService:
    API_VERSION = "v21.0"
    BASE_URL = "https://graph.facebook.com"

    def __init__(self):
        self.app_id = os.getenv("META_APP_ID", "")
        self.app_secret = os.getenv("META_APP_SECRET", "")
        self.access_token = os.getenv("META_ACCESS_TOKEN", "")
        self.ad_account_id = os.getenv("META_AD_ACCOUNT_ID", "")
        self.pixel_id = os.getenv("META_PIXEL_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.access_token and self.ad_account_id)

    def _api_url(self, endpoint: str) -> str:
        return f"{self.BASE_URL}/{self.API_VERSION}/{endpoint}"

    def create_campaign(self, campaign_config, db=None) -> str:
        if not self.is_configured:
            import random
            return f"meta_sim_{random.randint(10000, 99999)}"

        try:
            import httpx
            campaign_data = {
                "name": campaign_config.name if hasattr(campaign_config, 'name') else campaign_config.get("campaign_name", ""),
                "objective": "OUTCOME_SALES",
                "status": "PAUSED",
                "special_ad_categories": [],
                "access_token": self.access_token,
            }
            response = httpx.post(self._api_url(f"act_{self.ad_account_id}/campaigns"), data=campaign_data)
            response.raise_for_status()
            return response.json()["id"]
        except Exception as e:
            logger.error(f"Failed to create Meta campaign: {e}")
            return None

    def exchange_token(self, short_token: str, db) -> Dict:
        try:
            import httpx
            response = httpx.get(self._api_url("oauth/access_token"), params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_token,
            })
            response.raise_for_status()
            long_token = response.json().get("access_token")
            if long_token:
                from app.database import MetaTokenModel
                existing = db.query(MetaTokenModel).first()
                if existing:
                    existing.access_token = long_token
                else:
                    db.add(MetaTokenModel(access_token=long_token, token_type="long_lived"))
                db.commit()
                return {"token_type": "long_lived"}
            return {"error": "No token in response"}
        except Exception as e:
            return {"error": str(e)}

    def get_performance(self, db=None, days: int = 7) -> List[Dict]:
        if not self.is_configured:
            return []
        try:
            import httpx
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")
            params = {
                "fields": "campaign_id,campaign_name,impressions,clicks,spend,actions,action_values",
                "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
                "level": "campaign",
                "access_token": self.access_token,
            }
            response = httpx.get(self._api_url(f"act_{self.ad_account_id}/insights"), params=params)
            response.raise_for_status()
            results = []
            for row in response.json().get("data", []):
                conversions, revenue = 0, 0.0
                for a in row.get("actions", []):
                    if a.get("action_type") == "purchase":
                        conversions = int(a.get("value", 0))
                for av in row.get("action_values", []):
                    if av.get("action_type") == "purchase":
                        revenue = float(av.get("value", 0))
                results.append({
                    "campaign_id": row.get("campaign_id"), "campaign_name": row.get("campaign_name"),
                    "impressions": int(row.get("impressions", 0)), "clicks": int(row.get("clicks", 0)),
                    "spend": float(row.get("spend", 0)), "conversions": conversions, "revenue": revenue,
                })
            return results
        except Exception as e:
            logger.error(f"Meta performance fetch failed: {e}")
            return []

    def sync_performance(self, db) -> Dict:
        data = self.get_performance(db)
        if not data:
            return {"synced": 0, "message": "No data or not configured"}
        from app.database import CampaignModel
        synced = 0
        for row in data:
            campaign = db.query(CampaignModel).filter(
                CampaignModel.platform_campaign_id == row["campaign_id"]
            ).first()
            if campaign:
                campaign.spend = row["spend"]
                campaign.revenue = row["revenue"]
                campaign.conversions = row["conversions"]
                campaign.roas = row["revenue"] / row["spend"] if row["spend"] > 0 else 0
                synced += 1
        db.commit()
        return {"synced": synced}

    def update_campaign_budget(self, adset_id: str, new_budget: float) -> Dict:
        if not self.is_configured:
            return {"success": True, "simulated": True}
        try:
            import httpx
            response = httpx.post(self._api_url(adset_id),
                data={"daily_budget": int(new_budget * 100), "access_token": self.access_token})
            response.raise_for_status()
            return {"success": True, "new_budget": new_budget}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pause_campaign(self, campaign_id: str) -> Dict:
        if not self.is_configured:
            return {"success": True, "simulated": True}
        try:
            import httpx
            response = httpx.post(self._api_url(campaign_id),
                data={"status": "PAUSED", "access_token": self.access_token})
            response.raise_for_status()
            return {"success": True, "status": "paused"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_account_info(self) -> Dict:
        if not self.is_configured:
            return {"configured": False}
        try:
            import httpx
            response = httpx.get(self._api_url(f"act_{self.ad_account_id}"),
                params={"fields": "name,account_status,currency,timezone_name", "access_token": self.access_token})
            response.raise_for_status()
            return {"configured": True, **response.json()}
        except Exception as e:
            return {"configured": True, "error": str(e)}
