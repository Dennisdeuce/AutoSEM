from typing import List
from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.models import Campaign
from app.schemas.campaign import CampaignCreate, CampaignUpdate


class CRUDCampaign(CRUDBase[Campaign, CampaignCreate, CampaignUpdate]):
    def get_by_platform_id(self, db: Session, *, platform_campaign_id: str) -> Campaign:
        return db.query(Campaign).filter(Campaign.platform_campaign_id == platform_campaign_id).first()

    def get_active_campaigns(self, db: Session) -> List[Campaign]:
        return db.query(Campaign).filter(Campaign.status == "ACTIVE").all()

    def get_campaigns_by_platform(self, db: Session, *, platform: str) -> List[Campaign]:
        return db.query(Campaign).filter(Campaign.platform == platform).all()


campaign = CRUDCampaign(Campaign)