"""
Pydantic schemas for AutoSEM API
"""

from typing import Optional, List
from pydantic import BaseModel


# --- Products ---

class ProductBase(BaseModel):
    shopify_id: str
    title: str
    description: Optional[str] = None
    handle: Optional[str] = None
    product_type: Optional[str] = None
    vendor: Optional[str] = None
    price: Optional[float] = None
    compare_at_price: Optional[float] = None
    cost_price: Optional[float] = None
    gross_margin: Optional[float] = None
    inventory_quantity: Optional[int] = 0
    is_available: Optional[bool] = True
    images: Optional[str] = None
    variants: Optional[str] = None
    tags: Optional[str] = None


class ProductCreate(ProductBase):
    pass


class Product(ProductBase):
    id: int

    class Config:
        from_attributes = True


# --- Campaigns ---

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

    class Config:
        from_attributes = True


# --- Settings ---

class SettingsResponse(BaseModel):
    daily_spend_limit: float = 200.0
    monthly_spend_limit: float = 5000.0
    min_roas_threshold: float = 1.5
    emergency_pause_loss: float = 500.0


# --- Meta ---

class TokenUpdate(BaseModel):
    access_token: str
