from typing import Optional
from pydantic import BaseModel


class CampaignBase(BaseModel):
    platform: str
    platform_campaign_id: Optional[str] = None
    name: str
    status: Optional[str] = "ACTIVE"
    campaign_type: Optional[str] = None
    product_id: Optional[int] = None
    daily_budget: Optional[float] = None
    target_cpa: Optional[float] = None
    target_roas: Optional[float] = None
    spend: Optional[float] = 0.0
    revenue: Optional[float] = 0.0
    conversions: Optional[int] = 0
    roas: Optional[float] = 0.0


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(CampaignBase):
    pass


class Campaign(CampaignBase):
    id: int

    class Config:
        from_attributes = True