import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.crud import product, campaign
from app.models import Product
from app.schemas.campaign import CampaignCreate
from app.services.bidding import bidding_engine
from app.services.google_ads import google_ads_service
from app.services.meta_ads import meta_ads_service
from app.services.creative import creative_engine

logger = logging.getLogger(__name__)


class CampaignCreationService:
    def __init__(self, db: Session):
        self.db = db

    def create_campaigns_for_product(self, product: Product) -> List[str]:
        """Create all relevant campaigns for a product"""
        created_campaigns = []

        # Calculate bidding parameters
        target_cpa = bidding_engine.calculate_target_cpa(product)
        target_roas = bidding_engine.calculate_target_roas(product)

        # Google Ads campaigns
        google_campaigns = self._create_google_campaigns_for_product(product, target_cpa, target_roas)
        created_campaigns.extend(google_campaigns)

        # Meta Ads campaigns
        meta_campaigns = self._create_meta_campaigns_for_product(product, target_cpa, target_roas)
        created_campaigns.extend(meta_campaigns)

        return created_campaigns

    def _create_google_campaigns_for_product(self, product: Product, target_cpa: float, target_roas: float) -> List[str]:
        """Create Google Ads campaigns for a product"""
        campaigns_created = []

        # Brand campaign (if product has brand terms)
        if product.vendor and product.vendor.lower() not in ['generic', 'unknown']:
            brand_campaign = self._create_google_brand_campaign(product, target_cpa)
            if brand_campaign:
                campaigns_created.append(f"google:{brand_campaign}")

        # Shopping campaign
        shopping_campaign = self._create_google_shopping_campaign(product, target_roas)
        if shopping_campaign:
            campaigns_created.append(f"google:{shopping_campaign}")

        # Performance Max campaign
        pmax_campaign = self._create_google_pmax_campaign(product, target_roas)
        if pmax_campaign:
            campaigns_created.append(f"google:{pmax_campaign}")

        # Non-brand search campaign
        search_campaign = self._create_google_search_campaign(product, target_cpa)
        if search_campaign:
            campaigns_created.append(f"google:{search_campaign}")

        return campaigns_created

    def _create_google_brand_campaign(self, product: Product, target_cpa: float) -> Optional[str]:
        """Create brand protection campaign"""
        campaign_data = {
            'name': f"[BRAND] {product.vendor} - Brand Terms",
            'campaign_type': 'SEARCH',
            'daily_budget': 50.0,  # Conservative budget for brand
            'target_cpa': target_cpa,
            'target_roas': None
        }

        campaign_id = google_ads_service.create_campaign(campaign_data)
        if campaign_id:
            # Save to database
            db_campaign = CampaignCreate(
                platform='google',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='BRAND',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_cpa=target_cpa
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Google brand campaign for {product.title}")

        return campaign_id

    def _create_google_shopping_campaign(self, product: Product, target_roas: float) -> Optional[str]:
        """Create shopping campaign"""
        campaign_data = {
            'name': f"[SHOPPING] {product.product_type} - {product.vendor}",
            'campaign_type': 'SHOPPING',
            'daily_budget': 100.0,
            'target_cpa': None,
            'target_roas': target_roas
        }

        campaign_id = google_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='google',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='SHOPPING',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_roas=target_roas
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Google shopping campaign for {product.title}")

        return campaign_id

    def _create_google_pmax_campaign(self, product: Product, target_roas: float) -> Optional[str]:
        """Create Performance Max campaign"""
        campaign_data = {
            'name': f"[PMAX] {product.product_type} - Full Catalog",
            'campaign_type': 'PMAX',
            'daily_budget': 75.0,
            'target_cpa': None,
            'target_roas': target_roas
        }

        campaign_id = google_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='google',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='PMAX',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_roas=target_roas
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Google PMAX campaign for {product.title}")

        return campaign_id

    def _create_google_search_campaign(self, product: Product, target_cpa: float) -> Optional[str]:
        """Create non-brand search campaign"""
        campaign_data = {
            'name': f"[SEARCH] {product.product_type} - High Intent",
            'campaign_type': 'SEARCH',
            'daily_budget': 60.0,
            'target_cpa': target_cpa,
            'target_roas': None
        }

        campaign_id = google_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='google',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='SEARCH',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_cpa=target_cpa
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Google search campaign for {product.title}")

        return campaign_id

    def _create_meta_campaigns_for_product(self, product: Product, target_cpa: float, target_roas: float) -> List[str]:
        """Create Meta Ads campaigns for a product"""
        campaigns_created = []

        # Prospecting campaign
        prospecting_campaign = self._create_meta_prospecting_campaign(product, target_cpa)
        if prospecting_campaign:
            campaigns_created.append(f"meta:{prospecting_campaign}")

        # Retargeting campaign
        retargeting_campaign = self._create_meta_retargeting_campaign(product, target_cpa)
        if retargeting_campaign:
            campaigns_created.append(f"meta:{retargeting_campaign}")

        # DPA campaign
        dpa_campaign = self._create_meta_dpa_campaign(product, target_roas)
        if dpa_campaign:
            campaigns_created.append(f"meta:{dpa_campaign}")

        return campaigns_created

    def _create_meta_prospecting_campaign(self, product: Product, target_cpa: float) -> Optional[str]:
        """Create prospecting campaign with broad interest targeting"""
        campaign_data = {
            'name': f"[PROSPECTING] {product.product_type} - Broad Interest",
            'campaign_type': 'PROSPECTING',
            'daily_budget': 40.0,
            'target_cpa': target_cpa
        }

        campaign_id = meta_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='meta',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='PROSPECTING',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_cpa=target_cpa
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Meta prospecting campaign for {product.title}")

        return campaign_id

    def _create_meta_retargeting_campaign(self, product: Product, target_cpa: float) -> Optional[str]:
        """Create retargeting campaign"""
        campaign_data = {
            'name': f"[RETARGETING] {product.product_type} - Website Visitors",
            'campaign_type': 'RETARGETING',
            'daily_budget': 35.0,
            'target_cpa': target_cpa
        }

        campaign_id = meta_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='meta',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='RETARGETING',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_cpa=target_cpa
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Meta retargeting campaign for {product.title}")

        return campaign_id

    def _create_meta_dpa_campaign(self, product: Product, target_roas: float) -> Optional[str]:
        """Create Dynamic Product Ads campaign"""
        campaign_data = {
            'name': f"[DPA] {product.product_type} - Dynamic Product Ads",
            'campaign_type': 'DPA',
            'daily_budget': 45.0,
            'target_roas': target_roas
        }

        campaign_id = meta_ads_service.create_campaign(campaign_data)
        if campaign_id:
            db_campaign = CampaignCreate(
                platform='meta',
                platform_campaign_id=campaign_id,
                name=campaign_data['name'],
                campaign_type='DPA',
                product_id=product.id,
                daily_budget=campaign_data['daily_budget'],
                target_roas=target_roas
            )
            campaign.create(self.db, obj_in=db_campaign)
            logger.info(f"Created Meta DPA campaign for {product.title}")

        return campaign_id

    def create_all_campaigns_for_new_products(self) -> Dict[str, int]:
        """Create campaigns for all products that don't have campaigns yet"""
        products = product.get_available_products(self.db)
        stats = {'processed': 0, 'campaigns_created': 0}

        for prod in products:
            # Check if product already has campaigns
            existing_campaigns = campaign.get_multi(self.db, skip=0, limit=1000)
            product_campaigns = [c for c in existing_campaigns if c.product_id == prod.id]

            if not product_campaigns:
                created = self.create_campaigns_for_product(prod)
                stats['campaigns_created'] += len(created)
                stats['processed'] += 1

        logger.info(f"Campaign creation complete: {stats}")
        return stats


def get_campaign_creation_service(db: Session) -> CampaignCreationService:
    return CampaignCreationService(db)