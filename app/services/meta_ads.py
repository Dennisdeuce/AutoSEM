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
    """Interface with Meta Marketing API for campaign management."""

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

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def update_token(self, token: str):
        self.access_token = token

    def create_campaign(self, campaign_config: Dict) -> Dict:
        if not self.is_configured:
            return self._simulate_create(campaign_config)

        try:
            import httpx

            campaign_data = {
                "name": campaign_config["campaign_name"],
                "objective": "OUTCOME_SALES",
                "status": "PAUSED",
                "special_ad_categories": [],
                "access_token": self.access_token,
            }

            response = httpx.post(
                self._api_url(f"act_{self.ad_account_id}/campaigns"),
                data=campaign_data,
            )
            response.raise_for_status()
            campaign_id = response.json()["id"]

            daily_budget_cents = int(campaign_config.get("daily_budget", 10) * 100)
            targeting = campaign_config.get("targeting", {})

            adset_data = {
                "name": f"{campaign_config['campaign_name']} - Ad Set",
                "campaign_id": campaign_id,
                "daily_budget": daily_budget_cents,
                "billing_event": "IMPRESSIONS",
                "optimization_goal": targeting.get("optimization_goal", "CONVERSIONS"),
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "targeting": self._build_targeting_spec(targeting),
                "status": "PAUSED",
                "access_token": self.access_token,
            }

            if self.pixel_id:
                adset_data["promoted_object"] = f'{{"pixel_id": "{self.pixel_id}", "custom_event_type": "PURCHASE"}}'

            response = httpx.post(
                self._api_url(f"act_{self.ad_account_id}/adsets"),
                data=adset_data,
            )
            response.raise_for_status()
            adset_id = response.json()["id"]

            logger.info(f"Created Meta campaign {campaign_id} with ad set {adset_id}")

            return {
                "success": True,
                "external_id": campaign_id,
                "adset_id": adset_id,
                "status": "paused",
                "platform": "meta",
            }

        except ImportError:
            logger.warning("httpx not installed for Meta API calls")
            return self._simulate_create(campaign_config)
        except Exception as e:
            logger.error(f"Failed to create Meta campaign: {e}")
            return {
                "success": False,
                "error": str(e),
                "platform": "meta",
            }

    def _build_targeting_spec(self, targeting: Dict) -> str:
        import json

        age_range = targeting.get("age_range", "25-55")
        age_min, age_max = age_range.split("-") if "-" in age_range else ("25", "55")

        spec = {
            "age_min": int(age_min),
            "age_max": int(age_max),
            "geo_locations": {
                "countries": targeting.get("countries", ["US"]),
            },
            "publisher_platforms": ["facebook", "instagram"],
            "facebook_positions": ["feed"],
            "instagram_positions": ["stream", "story"],
        }

        interests = targeting.get("interests", [])
        if interests:
            spec["flexible_spec"] = [{
                "interests": [
                    {"id": "6003384912200", "name": "Tennis"},
                    {"id": "6003966441882", "name": "Sports clothing"},
                ]
            }]

        return json.dumps(spec)

    def update_campaign_budget(self, adset_id: str, new_budget: float) -> Dict:
        if not self.is_configured:
            return {"success": True, "simulated": True, "new_budget": new_budget}

        try:
            import httpx

            response = httpx.post(
                self._api_url(adset_id),
                data={
                    "daily_budget": int(new_budget * 100),
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            return {"success": True, "new_budget": new_budget}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pause_campaign(self, campaign_id: str) -> Dict:
        if not self.is_configured:
            return {"success": True, "simulated": True, "status": "paused"}

        try:
            import httpx

            response = httpx.post(
                self._api_url(campaign_id),
                data={
                    "status": "PAUSED",
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            return {"success": True, "status": "paused"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def enable_campaign(self, campaign_id: str) -> Dict:
        if not self.is_configured:
            return {"success": True, "simulated": True, "status": "active"}

        try:
            import httpx

            response = httpx.post(
                self._api_url(campaign_id),
                data={
                    "status": "ACTIVE",
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            return {"success": True, "status": "active"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_performance(self, campaign_id: str = None, days: int = 7) -> List[Dict]:
        if not self.is_configured:
            return []

        try:
            import httpx

            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")

            endpoint = f"act_{self.ad_account_id}/insights" if not campaign_id else f"{campaign_id}/insights"

            params = {
                "fields": "campaign_id,campaign_name,impressions,clicks,spend,actions,action_values",
                "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
                "level": "campaign",
                "access_token": self.access_token,
            }

            response = httpx.get(self._api_url(endpoint), params=params)
            response.raise_for_status()
            data = response.json().get("data", [])

            results = []
            for row in data:
                conversions = 0
                revenue = 0.0
                for action in row.get("actions", []):
                    if action.get("action_type") == "purchase":
                        conversions = int(action.get("value", 0))
                for action_value in row.get("action_values", []):
                    if action_value.get("action_type") == "purchase":
                        revenue = float(action_value.get("value", 0))

                results.append({
                    "campaign_id": row.get("campaign_id"),
                    "campaign_name": row.get("campaign_name"),
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "spend": float(row.get("spend", 0)),
                    "conversions": conversions,
                    "revenue": revenue,
                })

            return results

        except Exception as e:
            logger.error(f"Failed to fetch Meta Ads performance: {e}")
            return []

    def get_account_info(self) -> Dict:
        if not self.is_configured:
            return {"configured": False}

        try:
            import httpx

            response = httpx.get(
                self._api_url(f"act_{self.ad_account_id}"),
                params={
                    "fields": "name,account_status,currency,timezone_name,balance",
                    "access_token": self.access_token,
                },
            )
            response.raise_for_status()
            return {"configured": True, **response.json()}
        except Exception as e:
            return {"configured": True, "error": str(e)}

    def refresh_access_token(self) -> Optional[str]:
        if not self.app_id or not self.app_secret or not self.access_token:
            return None

        try:
            import httpx

            response = httpx.get(
                self._api_url("oauth/access_token"),
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "fb_exchange_token": self.access_token,
                },
            )
            response.raise_for_status()
            new_token = response.json().get("access_token")
            if new_token:
                self.access_token = new_token
                return new_token
            return None
        except Exception as e:
            logger.error(f"Failed to refresh Meta token: {e}")
            return None

    def _simulate_create(self, config: Dict) -> Dict:
        import random
        sim_id = f"meta_sim_{random.randint(10000, 99999)}"
        logger.info(f"Simulated Meta campaign creation: {sim_id}")
        return {
            "success": True,
            "external_id": sim_id,
            "adset_id": f"adset_{sim_id}",
            "status": "draft",
            "platform": "meta",
            "simulated": True,
        }
