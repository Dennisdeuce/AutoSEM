from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    shopify_id = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    handle = Column(String)
    product_type = Column(String)
    vendor = Column(String)
    price = Column(Float)
    compare_at_price = Column(Float)
    cost_price = Column(Float)  # From Printful
    gross_margin = Column(Float)
    inventory_quantity = Column(Integer, default=0)
    is_available = Column(Boolean, default=True)
    images = Column(Text)  # JSON string of image URLs
    variants = Column(Text)  # JSON string of variants
    tags = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    campaigns = relationship("Campaign", back_populates="product")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False)  # google, meta, microsoft
    platform_campaign_id = Column(String, unique=True)
    name = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")  # ACTIVE, PAUSED, REMOVED
    campaign_type = Column(String)  # SEARCH, SHOPPING, PMAXX, PROSPECTING, RETARGETING, DPA
    product_id = Column(Integer, ForeignKey("products.id"))
    daily_budget = Column(Float)
    target_cpa = Column(Float)
    target_roas = Column(Float)
    spend = Column(Float, default=0.0)
    revenue = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    roas = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    product = relationship("Product", back_populates="campaigns")
    ads = relationship("Ad", back_populates="campaign")


class Ad(Base):
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True, index=True)
    platform_ad_id = Column(String, unique=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    name = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")
    headline = Column(String)
    description = Column(String)
    image_url = Column(String)
    spend = Column(Float, default=0.0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    roas = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    campaign = relationship("Campaign", back_populates="ads")


class OptimizationLog(Base):
    __tablename__ = "optimization_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)
    entity_type = Column(String)  # campaign, ad, keyword
    entity_id = Column(String)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())