from typing import Optional
from pydantic import BaseModel


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


class ProductUpdate(ProductBase):
    pass


class Product(ProductBase):
    id: int

    class Config:
        from_attributes = True