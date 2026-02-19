"""Meta Ads Service
Manages Meta (Facebook/Instagram) ad campaigns and performance syncing.
v1.1 - Added appsecret_proof (HMAC-SHA256) for all Graph API calls
"""
import os
import hmac
import hashlib
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

    def _compute_proof(self) -> str:
        """Bug 6 fix: Compute appsecret_proof = HMAC-SHA256(access_token, app_secret).
        Required by Meta Graph API when appsecret_proof is enforced.
        """
        if not self.app_secret or not self.access_token:
            return ""
        return hmac.new(
            self.app_secret.encode("utf-8"),
            self.access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _auth_params(self) -> Dict:
        """Return auth params dict including appsecret_proof."""
        params = {"access_token": self.access_token}
        proof = self._compute_proof()
        if proof:
            params["appsecret_proof"] = proof
        return params

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _api_get(self, endpoint: str, params: Dict = None):
        """Make a retried GET request to the Graph API."""
        from app.services.retry import with_retry
        import httpx

        @with_retry(retries=3, backoff=1.0)
        def _do():
            resp = httpx.get(self._api_url(endpoint), params=params or {}, timeout=30)
            resp.raise_for_status()
            return resp.json()

        return _do()

    def _api_post(self, endpoint: str, data: Dict = None):
        """Make a retried POST request to the Graph API."""
        from app.services.retry import with_retry
        import httpx

        @with_retry(retries=3, backoff=1.0)
        def _do():
            resp = httpx.post(self._api_url(endpoint), data=data or {}, timeout=30)
            resp.raise_for_status()
            return resp.json()

        return _do()

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
                **self._auth_params(),
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
                **self._auth_params(),
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
                    **self._auth_params(),
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
                    **self._auth_params(),
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
                    **self._auth_params(),
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
                **self._auth_params(),
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
                    **self._auth_params(),
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

    def exchange_token(self, short_lived_token: str, db=None) -> Dict:
        """Exchange a short-lived token for a long-lived one."""
        if not self.app_id or not self.app_secret:
            return {"error": "META_APP_ID and META_APP_SECRET required"}

        try:
            import httpx

            response = httpx.get(
                self._api_url("oauth/access_token"),
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "fb_exchange_token": short_lived_token,
                },
            )
            response.raise_for_status()
            data = response.json()
            new_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 0)

            if new_token:
                self.access_token = new_token
                # Persist to DB if available
                if db:
                    from app.database import MetaTokenModel
                    token_record = db.query(MetaTokenModel).first()
                    if token_record:
                        token_record.access_token = new_token
                        token_record.expires_in = expires_in
                        token_record.updated_at = datetime.utcnow()
                    else:
                        token_record = MetaTokenModel(
                            access_token=new_token,
                            expires_in=expires_in,
                        )
                        db.add(token_record)
                    db.commit()

                return {
                    "token_exchanged": True,
                    "expires_in": expires_in,
                    "token_prefix": new_token[:12] + "...",
                }

            return {"error": "No token returned"}

        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return {"error": str(e)}

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
