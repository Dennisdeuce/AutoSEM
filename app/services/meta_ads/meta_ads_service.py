import logging
from typing import List, Dict, Any, Optional
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign as MetaCampaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.exceptions import FacebookRequestError
from app.core.config import settings

logger = logging.getLogger(__name__)


class MetaAdsService:
    def __init__(self):
        self.api = None
        self.ad_account_id = settings.META_AD_ACCOUNT_ID

        if all([
            settings.META_APP_ID,
            settings.META_APP_SECRET,
            settings.META_ACCESS_TOKEN
        ]):
            try:
                FacebookAdsApi.init(
                    app_id=settings.META_APP_ID,
                    app_secret=settings.META_APP_SECRET,
                    access_token=settings.META_ACCESS_TOKEN
                )
                self.api = FacebookAdsApi.get_default_api()
                logger.info("Meta Ads API initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Meta Ads API: {e}")
        else:
            logger.warning("Meta Ads credentials not fully configured")

    def create_campaign(self, campaign_data: Dict[str, Any]) -> Optional[str]:
        """Create a new Meta Ads campaign"""
        if not self.api:
            logger.error("Meta Ads API not initialized")
            return None

        try:
            account = AdAccount(f'act_{self.ad_account_id}')

            campaign_params = {
                'name': campaign_data['name'],
                'objective': self._get_objective(campaign_data.get('campaign_type', 'CONVERSIONS')),
                'status': 'PAUSED',
                'special_ad_categories': [],
            }

            # Set campaign budget
            if campaign_data.get('daily_budget'):
                campaign_params['daily_budget'] = str(int(campaign_data['daily_budget'] * 100))

            campaign = account.create_campaign(params=campaign_params)
            campaign_id = campaign.get_id()

            logger.info(f"Created Meta Ads campaign: {campaign_id}")
            return campaign_id

        except FacebookRequestError as e:
            logger.error(f"Meta Ads API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating Meta campaign: {e}")
            return None

    def create_adset(self, campaign_id: str, adset_data: Dict[str, Any]) -> Optional[str]:
        """Create an ad set within a campaign"""
        if not self.api:
            return None

        try:
            campaign = MetaCampaign(campaign_id)

            adset_params = {
                'name': adset_data['name'],
                'campaign_id': campaign_id,
                'status': 'PAUSED',
                'billing_event': 'IMPRESSIONS',
                'optimization_goal': 'CONVERSIONS',
                'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
            }

            # Set targeting
            if adset_data.get('targeting'):
                adset_params['targeting'] = adset_data['targeting']

            # Set budget
            if adset_data.get('daily_budget'):
                adset_params['daily_budget'] = str(int(adset_data['daily_budget'] * 100))

            adset = campaign.create_ad_set(params=adset_params)
            adset_id = adset.get_id()

            logger.info(f"Created Meta Ads adset: {adset_id}")
            return adset_id

        except Exception as e:
            logger.error(f"Error creating adset: {e}")
            return None

    def create_ad(self, adset_id: str, ad_data: Dict[str, Any]) -> Optional[str]:
        """Create an ad within an ad set"""
        if not self.api:
            return None

        try:
            adset = AdSet(adset_id)

            ad_params = {
                'name': ad_data['name'],
                'adset_id': adset_id,
                'status': 'PAUSED',
                'creative': {
                    'title': ad_data.get('headline', ''),
                    'body': ad_data.get('description', ''),
                    'image_url': ad_data.get('image_url', ''),
                    'link_url': ad_data.get('link_url', ''),
                }
            }

            ad = adset.create_ad(params=ad_params)
            ad_id = ad.get_id()

            logger.info(f"Created Meta Ads ad: {ad_id}")
            return ad_id

        except Exception as e:
            logger.error(f"Error creating ad: {e}")
            return None

    def update_campaign_budget(self, campaign_id: str, budget: float) -> bool:
        """Update campaign budget"""
        if not self.api:
            return False

        try:
            campaign = MetaCampaign(campaign_id)
            campaign.update({
                'daily_budget': str(int(budget * 100))
            })

            logger.info(f"Updated budget for campaign {campaign_id} to ${budget}")
            return True

        except Exception as e:
            logger.error(f"Error updating campaign budget: {e}")
            return False

    def pause_adset(self, adset_id: str) -> bool:
        """Pause an ad set"""
        if not self.api:
            return False

        try:
            adset = AdSet(adset_id)
            adset.update({
                'status': 'PAUSED'
            })

            logger.info(f"Paused adset: {adset_id}")
            return True

        except Exception as e:
            logger.error(f"Error pausing adset: {e}")
            return False

    def get_campaign_insights(self, campaign_id: str, days: int = 30) -> Dict[str, Any]:
        """Get campaign performance insights"""
        if not self.api:
            return {}

        try:
            campaign = MetaCampaign(campaign_id)
            params = {
                'time_range': {'since': f'{days} days ago', 'until': 'now'},
                'level': 'campaign',
                'fields': [
                    'impressions', 'clicks', 'spend', 'conversions',
                    'cost_per_conversion', 'conversion_rate_ranking',
                    'quality_ranking', 'engagement_rate_ranking'
                ]
            }

            insights = campaign.get_insights(params=params)

            if insights:
                data = insights[0]
                return {
                    'impressions': int(data.get('impressions', 0)),
                    'clicks': int(data.get('clicks', 0)),
                    'spend': float(data.get('spend', 0)),
                    'conversions': float(data.get('conversions', 0)),
                    'cost_per_conversion': float(data.get('cost_per_conversion', 0)),
                    'roas': data.get('conversion_rate_ranking', 'N/A'),
                    'quality_score': data.get('quality_ranking', 'N/A'),
                    'engagement_score': data.get('engagement_rate_ranking', 'N/A')
                }

            return {}

        except Exception as e:
            logger.error(f"Error getting campaign insights: {e}")
            return {}

    def create_lookalike_audience(self, source_audience_id: str, name: str, ratio: str = '1%') -> Optional[str]:
        """Create a lookalike audience"""
        if not self.api:
            return None

        try:
            account = AdAccount(f'act_{self.ad_account_id}')

            audience_params = {
                'name': name,
                'subtype': 'LOOKALIKE',
                'lookalike_spec': {
                    'origin': {
                        'id': source_audience_id,
                        'type': 'CUSTOM_AUDIENCE'
                    },
                    'country': 'US',
                    'ratio': ratio,
                    'starting_ratio': 1
                }
            }

            audience = account.create_custom_audience(params=audience_params)
            audience_id = audience.get_id()

            logger.info(f"Created lookalike audience: {audience_id}")
            return audience_id

        except Exception as e:
            logger.error(f"Error creating lookalike audience: {e}")
            return None

    def _get_objective(self, campaign_type: str) -> str:
        """Map campaign type to Meta objective"""
        mapping = {
            'PROSPECTING': 'CONVERSIONS',
            'RETARGETING': 'CONVERSIONS',
            'DPA': 'CONVERSIONS',
            'BRAND': 'BRAND_AWARENESS',
            'TRAFFIC': 'TRAFFIC'
        }
        return mapping.get(campaign_type.upper(), 'CONVERSIONS')


meta_ads_service = MetaAdsService()