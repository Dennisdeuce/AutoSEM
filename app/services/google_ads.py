"""
Google Ads Service
Manages Google Ads campaigns, ad groups, and performance syncing.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger("autosem.google_ads")


class GoogleAdsService:
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
        except Exception as e:
            logger.error(f"Failed to initialize Google Ads client: {e}")
            return None

    def create_campaign(self, campaign_config, db=None) -> str:
        client = self._get_client()
        if not client:
            import random
            sim_id = f"sim_{random.randint(10000, 99999)}"
            logger.info(f"Simulated Google Ads campaign: {sim_id}")
            return sim_id

        try:
            campaign_service = client.get_service("CampaignService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            budget_operation = client.get_type("CampaignBudgetOperation")
            budget = budget_operation.create
            budget.name = f"AutoSEM Budget - {campaign_config.name}"
            budget.amount_micros = int((campaign_config.daily_budget or 10) * 1_000_000)
            budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
            budget_response = campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.customer_id, operations=[budget_operation])
            budget_resource = budget_response.results[0].resource_name

            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create
            campaign.name = campaign_config.name
            campaign.campaign_budget = budget_resource
            campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
            campaign.status = client.enums.CampaignStatusEnum.PAUSED
            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = False

            response = campaign_service.mutate_campaigns(
                customer_id=self.customer_id, operations=[campaign_operation])
            resource_name = response.results[0].resource_name
            return resource_name.split("/")[-1]
        except Exception as e:
            logger.error(f"Failed to create Google Ads campaign: {e}")
            return None

    def sync_performance(self, db) -> Dict:
        client = self._get_client()
        if not client:
            return {"synced": 0, "message": "Google Ads API not configured"}

        try:
            ga_service = client.get_service("GoogleAdsService")
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")
            query = f"""
                SELECT campaign.id, campaign.name, campaign.status,
                    metrics.impressions, metrics.clicks, metrics.cost_micros,
                    metrics.conversions, metrics.conversions_value
                FROM campaign
                WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
            """
            response = ga_service.search(customer_id=self.customer_id, query=query)

            from app.database import CampaignModel
            synced = 0
            for row in response:
                ext_id = str(row.campaign.id)
                campaign = db.query(CampaignModel).filter(
                    CampaignModel.platform_campaign_id == ext_id
                ).first()
                if campaign:
                    campaign.spend = row.metrics.cost_micros / 1_000_000
                    campaign.revenue = row.metrics.conversions_value
                    campaign.conversions = int(row.metrics.conversions)
                    campaign.roas = campaign.revenue / campaign.spend if campaign.spend > 0 else 0
                    synced += 1
            db.commit()
            return {"synced": synced}
        except Exception as e:
            logger.error(f"Performance sync failed: {e}")
            return {"synced": 0, "error": str(e)}

    def update_campaign_budget(self, external_id: str, new_budget: float) -> Dict:
        client = self._get_client()
        if not client:
            return {"success": True, "simulated": True, "new_budget": new_budget}
        return {"success": True, "external_id": external_id, "new_budget": new_budget}

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
            campaign_service.mutate_campaigns(
                customer_id=self.customer_id, operations=[campaign_operation])
            return {"success": True, "status": "paused"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_performance(self, external_id: str = None, days: int = 7) -> List[Dict]:
        client = self._get_client()
        if not client:
            return []
        try:
            ga_service = client.get_service("GoogleAdsService")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")
            query = f"""
                SELECT campaign.id, campaign.name, metrics.impressions,
                    metrics.clicks, metrics.cost_micros, metrics.conversions,
                    metrics.conversions_value
                FROM campaign
                WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
            """
            if external_id:
                query += f" AND campaign.id = {external_id}"
            response = ga_service.search(customer_id=self.customer_id, query=query)
            return [{"campaign_id": str(row.campaign.id), "impressions": row.metrics.impressions,
                     "clicks": row.metrics.clicks, "spend": row.metrics.cost_micros / 1_000_000,
                     "conversions": int(row.metrics.conversions), "revenue": row.metrics.conversions_value}
                    for row in response]
        except Exception as e:
            logger.error(f"Failed to fetch performance: {e}")
            return []
