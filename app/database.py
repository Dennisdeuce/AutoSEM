"""Database configuration and SQLAlchemy models"""

import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, DateTime, Date, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("autosem.database")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./autosem.db")

# Handle postgres:// vs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Build engine with appropriate settings
if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """Add missing columns to existing tables (safe to run multiple times)."""
    migrations = [
        ("campaigns", "impressions", "INTEGER DEFAULT 0"),
        ("campaigns", "clicks", "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info(f"Migration: added {table}.{column}")
            except Exception:
                conn.rollback()  # Column already exists, skip


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
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
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
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


class CampaignHistoryModel(Base):
    __tablename__ = "campaign_history"
    __table_args__ = (
        UniqueConstraint("campaign_id", "date", name="uq_campaign_history_campaign_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    date = Column(Date, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)


class PerformanceSnapshotModel(Base):
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "campaign_id", name="uq_snapshot_date_campaign"),
    )

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    platform = Column(String, nullable=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    spend = Column(Float, default=0.0)
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)


class TikTokTokenModel(Base):
    __tablename__ = "tiktok_tokens"

    id = Column(Integer, primary_key=True, index=True)
    access_token = Column(Text, nullable=True)
    advertiser_id = Column(String, nullable=True)
    advertiser_ids = Column(Text, nullable=True)  # JSON list
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ABTestModel(Base):
    __tablename__ = "ab_tests"

    id = Column(Integer, primary_key=True, index=True)
    test_name = Column(String, nullable=False)
    campaign_id = Column(String, nullable=True)  # Meta campaign ID
    original_ad_id = Column(String, nullable=False, index=True)
    variant_ad_id = Column(String, nullable=True, index=True)
    original_adset_id = Column(String, nullable=True)
    variant_adset_id = Column(String, nullable=True)
    variant_type = Column(String, nullable=False)  # headline, image, cta
    variant_value = Column(Text, nullable=True)  # The modified value
    status = Column(String, default="running")  # running, completed, winner_original, winner_variant, error
    confidence_level = Column(Float, default=0.0)  # 0-100%
    winner = Column(String, nullable=True)  # original, variant, inconclusive
    original_budget_cents = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
