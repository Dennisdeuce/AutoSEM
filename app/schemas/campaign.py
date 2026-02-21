from typing import Optional
from pydantic import BaseModel, model_validator


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
    total_spend: Optional[float] = 0.0
    total_revenue: Optional[float] = 0.0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0
    conversions: Optional[int] = 0
    roas: Optional[float] = 0.0
    headlines: Optional[str] = None
    descriptions: Optional[str] = None
    keywords: Optional[str] = None


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(CampaignBase):
    pass


class Campaign(CampaignBase):
    id: int
    ctr: Optional[float] = 0.0
    cpc: Optional[float] = 0.0

    @model_validator(mode="after")
    def compute_metrics(self):
        impressions = self.impressions or 0
        clicks = self.clicks or 0
        spend = self.spend or 0.0
        self.ctr = round((clicks / impressions) * 100, 2) if impressions > 0 else 0.0
        self.cpc = round(spend / clicks, 2) if clicks > 0 else 0.0
        return self

    class Config:
        from_attributes = True