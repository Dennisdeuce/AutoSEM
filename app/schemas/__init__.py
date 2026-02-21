from .product import Product, ProductCreate, ProductUpdate
from .campaign import Campaign, CampaignCreate, CampaignUpdate, CampaignHistory
from pydantic import BaseModel


class TokenUpdate(BaseModel):
    access_token: str
