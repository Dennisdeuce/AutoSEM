import logging
from typing import List, Dict, Any, Optional
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from app.core.config import settings

logger = logging.getLogger(__name__)


class GoogleAdsService:
    def __init__(self):
        self.client = None
        self.customer_id = settings.GOOGLE_ADS_CUSTOMER_ID

        if all([
            settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            settings.GOOGLE_ADS_CLIENT_ID,
            settings.GOOGLE_ADS_CLIENT_SECRET,
            settings.GOOGLE_ADS_REFRESH_TOKEN,
            settings.GOOGLE_ADS_CUSTOMER_ID
        ]):
            try:
                credentials = {
                    "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                    "client_id": settings.GOOGLE_ADS_CLIENT_ID,
                    "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
                    "refresh_token": settings.GOOGLE_ADS_REFRESH_TOKEN,
                    "customer_id": settings.GOOGLE_ADS_CUSTOMER_ID
                }
                self.client = GoogleAdsClient.load_from_dict(credentials)
                logger.info("Google Ads client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google Ads client: {e}")
        else:
            logger.warning("Google Ads credentials not fully configured")

    def create_campaign(self, campaign_data: Dict[str, Any]) -> Optional[str]:
        """Create a new Google Ads campaign"""
        if not self.client:
            logger.error("Google Ads client not initialized")
            return None

        try:
            campaign_service = self.client.get_service("CampaignService")
            campaign_budget_service = self.client.get_service("CampaignBudgetService")

            # Create campaign budget
            campaign_budget_operation = self.client.get_type("CampaignBudgetOperation")
            campaign_budget = campaign_budget_operation.create
            campaign_budget.name = f"{campaign_data['name']} Budget"
            campaign_budget.delivery_method = self.client.enums.BudgetDeliveryMethodEnum.STANDARD
            campaign_budget.amount_micros = int(campaign_data['daily_budget'] * 1000000)

            # Create campaign budget
            budget_response = campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.customer_id,
                operations=[campaign_budget_operation]
            )
            budget_resource_name = budget_response.results[0].resource_name

            # Create campaign
            campaign_operation = self.client.get_type("CampaignOperation")
            campaign = campaign_operation.create
            campaign.name = campaign_data['name']
            campaign.advertising_channel_type = self._get_channel_type(campaign_data['campaign_type'])
            campaign.status = self.client.enums.CampaignStatusEnum.PAUSED
            campaign.manual_cpc.enhanced_cpc_enabled = True
            campaign.campaign_budget = budget_resource_name

            # Set bidding strategy
            if campaign_data.get('target_cpa'):
                campaign.manual_cpc.enhanced_cpc_enabled = False
                campaign.target_cpa.target_cpa_micros = int(campaign_data['target_cpa'] * 1000000)

            # Create campaign
            campaign_response = campaign_service.mutate_campaigns(
                customer_id=self.customer_id,
                operations=[campaign_operation]
            )

            campaign_id = campaign_response.results[0].resource_name.split('/')[-1]
            logger.info(f"Created Google Ads campaign: {campaign_id}")
            return campaign_id

        except GoogleAdsException as ex:
            logger.error(f"Google Ads API error: {ex}")
            return None
        except Exception as e:
            logger.error(f"Error creating campaign: {e}")
            return None

    def update_campaign_budget(self, campaign_id: str, budget: float) -> bool:
        """Update campaign budget"""
        if not self.client:
            return False

        try:
            campaign_budget_service = self.client.get_service("CampaignBudgetService")

            # Get current budget
            query = f"""
                SELECT campaign_budget.resource_name, campaign_budget.amount_micros
                FROM campaign
                WHERE campaign.id = {campaign_id}
            """

            response = self.client.get_service("GoogleAdsService").search(
                customer_id=self.customer_id, query=query
            )

            for row in response:
                budget_resource_name = row.campaign_budget.resource_name
                break

            # Update budget
            operation = self.client.get_type("CampaignBudgetOperation")
            operation.update.resource_name = budget_resource_name
            operation.update.amount_micros = int(budget * 1000000)
            operation.update_mask.paths.append("amount_micros")

            campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.customer_id,
                operations=[operation]
            )

            logger.info(f"Updated budget for campaign {campaign_id} to ${budget}")
            return True

        except Exception as e:
            logger.error(f"Error updating campaign budget: {e}")
            return False

    def pause_ad(self, ad_id: str) -> bool:
        """Pause an ad"""
        if not self.client:
            return False

        try:
            ad_group_ad_service = self.client.get_service("AdGroupAdService")

            operation = self.client.get_type("AdGroupAdOperation")
            operation.update.resource_name = f"customers/{self.customer_id}/adGroupAds/{ad_id}"
            operation.update.status = self.client.enums.AdGroupAdStatusEnum.PAUSED
            operation.update_mask.paths.append("status")

            ad_group_ad_service.mutate_ad_group_ads(
                customer_id=self.customer_id,
                operations=[operation]
            )

            logger.info(f"Paused ad: {ad_id}")
            return True

        except Exception as e:
            logger.error(f"Error pausing ad: {e}")
            return False

    def get_search_terms_report(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get search terms performance report"""
        if not self.client:
            return []

        try:
            query = f"""
                SELECT
                    search_term_view.search_term,
                    search_term_view.status,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.conversions,
                    metrics.cost_micros,
                    metrics.conversions_value
                FROM search_term_view
                WHERE segments.date DURING LAST_{days}_DAYS
                ORDER BY metrics.clicks DESC
                LIMIT 1000
            """

            response = self.client.get_service("GoogleAdsService").search(
                customer_id=self.customer_id, query=query
            )

            results = []
            for row in response:
                results.append({
                    "query": row.search_term_view.search_term,
                    "status": row.search_term_view.status.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "conversions": row.metrics.conversions,
                    "cost": row.metrics.cost_micros / 1000000,
                    "revenue": row.metrics.conversions_value
                })

            return results

        except Exception as e:
            logger.error(f"Error getting search terms report: {e}")
            return []

    def add_negative_keyword(self, keyword: str, match_type: str = "EXACT") -> bool:
        """Add negative keyword to campaigns"""
        if not self.client:
            return False

        try:
            campaign_criterion_service = self.client.get_service("CampaignCriterionService")

            # Get all campaign resource names
            query = "SELECT campaign.resource_name FROM campaign"
            response = self.client.get_service("GoogleAdsService").search(
                customer_id=self.customer_id, query=query
            )

            operations = []
            for row in response:
                operation = self.client.get_type("CampaignCriterionOperation")
                criterion = operation.create
                criterion.campaign = row.campaign.resource_name
                criterion.negative = True
                criterion.keyword.text = keyword
                criterion.keyword.match_type = self._get_match_type(match_type)
                operations.append(operation)

            if operations:
                campaign_criterion_service.mutate_campaign_criteria(
                    customer_id=self.customer_id,
                    operations=operations
                )

            logger.info(f"Added negative keyword: {keyword}")
            return True

        except Exception as e:
            logger.error(f"Error adding negative keyword: {e}")
            return False

    def add_keyword(self, keyword: str, match_type: str = "PHRASE", ad_group_id: str = None) -> bool:
        """Add positive keyword to ad group"""
        if not self.client or not ad_group_id:
            return False

        try:
            ad_group_criterion_service = self.client.get_service("AdGroupCriterionService")

            operation = self.client.get_type("AdGroupCriterionOperation")
            criterion = operation.create
            criterion.ad_group = f"customers/{self.customer_id}/adGroups/{ad_group_id}"
            criterion.keyword.text = keyword
            criterion.keyword.match_type = self._get_match_type(match_type)

            ad_group_criterion_service.mutate_ad_group_criteria(
                customer_id=self.customer_id,
                operations=[operation]
            )

            logger.info(f"Added keyword: {keyword} to ad group {ad_group_id}")
            return True

        except Exception as e:
            logger.error(f"Error adding keyword: {e}")
            return False

    def _get_channel_type(self, campaign_type: str):
        """Map campaign type to Google Ads channel type"""
        mapping = {
            "SEARCH": self.client.enums.AdvertisingChannelTypeEnum.SEARCH,
            "SHOPPING": self.client.enums.AdvertisingChannelTypeEnum.SHOPPING,
            "PMAX": self.client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX,
            "DISPLAY": self.client.enums.AdvertisingChannelTypeEnum.DISPLAY
        }
        return mapping.get(campaign_type.upper(), self.client.enums.AdvertisingChannelTypeEnum.SEARCH)

    def _get_match_type(self, match_type: str):
        """Map match type string to enum"""
        mapping = {
            "EXACT": self.client.enums.KeywordMatchTypeEnum.EXACT,
            "PHRASE": self.client.enums.KeywordMatchTypeEnum.PHRASE,
            "BROAD": self.client.enums.KeywordMatchTypeEnum.BROAD
        }
        return mapping.get(match_type.upper(), self.client.enums.KeywordMatchTypeEnum.PHRASE)


google_ads_service = GoogleAdsService()