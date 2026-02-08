"""
Database configuration and SQLAlchemy models
"""

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./autosem.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ProductModel(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    shopify_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    handle = Column(String, nullable=True)
    product_type = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    compare_at_price = Column(Float, nullable=True)
    cost_price = Column(Float, nullable=True)
    gross_margin = Column(Float, nullable=True)
    inventory_quantity = Column(Integer, default=0)
    is_available = Column(Boolean, default=True)
    images = Column(Text, nullable=True)
    variants = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CampaignModel(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False)
    platform_campaign_id = Column(String, nullable=True)
    name = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")
    campaign_type = Column(String, nullable=True)
    product_id = Column(Integer, nullable=True)
    daily_budget = Column(Float, nullable=True)
    target_cpa = Column(Float, nullable=True)
    target_roas = Column(Float, nullable=True)
    spend = Column(Float, default=0.0)
    revenue = Column(Float, default=0.0)
    total_spend = Column(Float, default=0.0)
    total_revenue = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    roas = Column(Float, default=0.0)
    headlines = Column(Text, nullable=True)
    descriptions = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActivityLogModel(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class SettingsModel(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MetaTokenModel(Base):
    __tablename__ = "meta_tokens"
    id = Column(Integer, primary_key=True, index=True)
    access_token = Column(Text, nullable=True)
    token_type = Column(String, default="long_lived")
    expires_at = Column(DateTime, nullable=True)
    ad_account_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
