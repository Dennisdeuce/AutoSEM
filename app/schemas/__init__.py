from .product import Product, ProductCreate, ProductUpdate
from .campaign import Campaign, CampaignCreate, CampaignUpdate
from pydantic import BaseModel


class TokenUpdate(BaseModel):
    access_token: str
