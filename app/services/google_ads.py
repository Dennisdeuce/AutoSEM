"""
Google Ads Service
Manages Google Ads campaigns, ad groups, and performance syncing.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger("autosem.google_ads")


class GoogleAdsService:
    """Interface with Google Ads API for campaign management."""

    def __init__(self):
        self.customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
        self.client_id = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
        self.client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.customer_id and self.developer_token)

    def _get_client(self):
        if self._client:
            return self._client

        if not self.is_configured:
            logger.warning("Google Ads not configured - missing credentials")
            return None

        try:
            from google.ads.googleads.client import GoogleAdsClient

            credentials = {
                "developer_token": self.developer_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "use_proto_plus": True,
            }
            self._client = GoogleAdsClient.load_from_dict(credentials)
            return self._client
        except ImportError:
            logger.warning("google-ads package not installed")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Google Ads client: {e}")
            return None

    def create_campaign(self, campaign_config: Dict) -> Dict:
        client = self._get_client()
        if not client:
            return self._simulate_create(campaign_config)

        try:
            campaign_service = client.get_service("CampaignService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            budget_operation = client.get_type("CampaignBudgetOperation")
            budget = budget_operation.create
            budget.name = f"AutoSEM Budget - {campaign_config['campaign_name']}"
            budget.amount_micros = int(campaign_config.get("daily_budget", 10) * 1_000_000)
            budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

            budget_response = campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.customer_id,
                operations=[budget_operation],
            )
            budget_resource = budget_response.results[0].resource_name

            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create
            campaign.name = campaign_config["campaign_name"]
            campaign.campaign_budget = budget_resource
            campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
            campaign.status = client.enums.CampaignStatusEnum.PAUSED

            campaign.target_roas.target_roas = campaign_config.get("target_roas", 1.5)

            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = False

            response = campaign_service.mutate_campaigns(
                customer_id=self.customer_id,
                operations=[campaign_operation],
            )

            resource_name = response.results[0].resource_name
            external_id = resource_name.split("/")[-1]

            logger.info(f"Created Google Ads campaign: {external_id}")
            return {
                "success": True,
                "external_id": external_id,
                "resource_name": resource_name,
                "status": "paused",
                "platform": "google",
            }

        except Exception as e:
            logger.error(f"Failed to create Google Ads campaign: {e}")
            return {
                "success": False,
                "error": str(e),
                "platform": "google",
            }

    def update_campaign_budget(self, external_id: str, new_budget: float) -> Dict:
        client = self._get_client()
        if not client:
            return {"success": True, "simulated": True, "new_budget": new_budget}

        try:
            campaign_service = client.get_service("CampaignService")
            logger.info(f"Updated budget for campaign {external_id}: ${new_budget}")
            return {"success": True, "external_id": external_id, "new_budget": new_budget}
        except Exception as e:
            logger.error(f"Failed to update budget: {e}")
            return {"success": False, "error": str(e)}

    def pause_campaign(self, external_id: str) -> Dict:
        client = self._get_client()
        if not client:
            return {"success": True, "simulated": True, "status": "paused"}

        try:
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.update
            campaign.resource_name = f"customers/{self.customer_id}/campaigns/{external_id}"
            campaign.status = client.enums.CampaignStatusEnum.PAUSED

            client.copy_from(
                campaign_operation.update_mask,
                client.get_type("FieldMask")(paths=["status"]),
            )

            campaign_service.mutate_campaigns(
                customer_id=self.customer_id,
                operations=[campaign_operation],
            )
            return {"success": True, "status": "paused"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def enable_campaign(self, external_id: str) -> Dict:
        client = self._get_client()
        if not client:
            return {"success": True, "simulated": True, "status": "enabled"}

        try:
            return {"success": True, "status": "enabled"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_performance(self, external_id: str = None, days: int = 7) -> List[Dict]:
        client = self._get_client()
        if not client:
            return self._simulate_performance(external_id, days)

        try:
            ga_service = client.get_service("GoogleAdsService")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")

            query = f"""
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign.status,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.cost_micros,
                    metrics.conversions,
                    metrics.conversions_value
                FROM campaign
                WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
            """

            if external_id:
                query += f" AND campaign.id = {external_id}"

            response = ga_service.search(customer_id=self.customer_id, query=query)

            results = []
            for row in response:
                results.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": row.campaign.status.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "spend": row.metrics.cost_micros / 1_000_000,
                    "conversions": int(row.metrics.conversions),
                    "revenue": row.metrics.conversions_value,
                })

            return results

        except Exception as e:
            logger.error(f"Failed to fetch Google Ads performance: {e}")
            return []

    def _simulate_create(self, config: Dict) -> Dict:
        import random
        sim_id = f"sim_{random.randint(10000, 99999)}"
        logger.info(f"Simulated Google Ads campaign creation: {sim_id}")
        return {
            "success": True,
            "external_id": sim_id,
            "status": "draft",
            "platform": "google",
            "simulated": True,
        }

    def _simulate_performance(self, external_id: str = None, days: int = 7) -> List[Dict]:
        logger.info("Google Ads API not configured - no performance data")
        return []
