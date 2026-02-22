"""Test fixtures for AutoSEM.

Provides:
- SQLite in-memory database (overrides get_db)
- FastAPI test client via httpx.AsyncClient
- Mocks for all external APIs (Meta, TikTok, Shopify, Klaviyo, Google)
- Seed data helpers
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Force SQLite before any app imports
os.environ["DATABASE_URL"] = "sqlite:///./test_autosem.db"
os.environ.setdefault("META_APP_ID", "test_app_id")
os.environ.setdefault("META_APP_SECRET", "test_app_secret")
os.environ.setdefault("META_AD_ACCOUNT_ID", "123456789")
os.environ.setdefault("META_ACCESS_TOKEN", "test_meta_token")
os.environ.setdefault("TIKTOK_ACCESS_TOKEN", "test_tiktok_token")
os.environ.setdefault("TIKTOK_ADVERTISER_ID", "test_tiktok_adv")
os.environ.setdefault("SHOPIFY_CLIENT_ID", "test_shopify_id")
os.environ.setdefault("SHOPIFY_CLIENT_SECRET", "test_shopify_secret")
os.environ.setdefault("KLAVIYO_API_KEY", "pk_test_klaviyo")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db

# In-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///./test_autosem.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    # Clean up test DB file
    import os
    try:
        os.remove("test_autosem.db")
    except OSError:
        pass


@pytest.fixture(autouse=True)
def clean_tables():
    """Truncate all tables between tests."""
    db = TestSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db_session():
    """Provide a clean DB session for tests that need direct DB access."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def client():
    """Synchronous TestClient for FastAPI."""
    # Patch scheduler to avoid background job startup
    with patch("scheduler.start_scheduler"), \
         patch("scheduler.stop_scheduler"):
        from main import create_app
        app = create_app()
        app.dependency_overrides[get_db] = override_get_db

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

        app.dependency_overrides.clear()


@pytest.fixture()
def seed_campaigns(db_session):
    """Insert sample campaigns for testing."""
    from app.database import CampaignModel
    campaigns = [
        CampaignModel(
            platform="meta",
            platform_campaign_id="120206746647300364",
            name="Test Active Campaign",
            status="ACTIVE",
            daily_budget=25.0,
            impressions=10000,
            clicks=430,
            spend=57.62,
            revenue=0,
            conversions=0,
            roas=0,
        ),
        CampaignModel(
            platform="meta",
            platform_campaign_id="120241759616260364",
            name="Test Paused Campaign",
            status="PAUSED",
            daily_budget=5.0,
            impressions=900,
            clicks=37,
            spend=25.50,
            revenue=0,
            conversions=0,
            roas=0,
        ),
        CampaignModel(
            platform="tiktok",
            platform_campaign_id="tt_campaign_001",
            name="TikTok Test Campaign",
            status="ACTIVE",
            daily_budget=10.0,
            impressions=5000,
            clicks=200,
            spend=30.0,
            revenue=120.0,
            conversions=3,
            roas=4.0,
        ),
    ]
    for c in campaigns:
        db_session.add(c)
    db_session.commit()
    return campaigns


@pytest.fixture()
def mock_meta_api():
    """Mock all Meta Graph API calls."""
    with patch("requests.get") as mock_get, \
         patch("requests.post") as mock_post:

        def _meta_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()

            if "/campaigns" in url and "insights" not in str(kwargs.get("params", {})):
                resp.json.return_value = {
                    "data": [
                        {
                            "id": "120206746647300364",
                            "name": "Test Campaign",
                            "status": "ACTIVE",
                            "daily_budget": "2500",
                            "objective": "LINK_CLICKS",
                        }
                    ]
                }
            elif "/insights" in url or "insights" in str(kwargs.get("params", {}).get("fields", "")):
                resp.json.return_value = {
                    "data": [
                        {
                            "spend": "57.62",
                            "impressions": "10000",
                            "clicks": "430",
                            "ctr": "4.30",
                            "cpc": "0.13",
                            "actions": [],
                        }
                    ]
                }
            elif "debug_token" in url:
                resp.json.return_value = {
                    "data": {"is_valid": True, "scopes": ["ads_management"], "expires_at": 9999999999}
                }
            else:
                resp.json.return_value = {"data": []}
            return resp

        def _meta_post(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"success": True, "id": "new_123"}
            return resp

        mock_get.side_effect = _meta_get
        mock_post.side_effect = _meta_post
        yield {"get": mock_get, "post": mock_post}


@pytest.fixture()
def mock_external_apis():
    """Mock all external API calls (Meta, TikTok, Shopify, Klaviyo)."""
    with patch("requests.get") as mock_get, \
         patch("requests.post") as mock_post, \
         patch("requests.delete") as mock_delete:

        def _generic_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.text = "{}"

            if "graph.facebook.com" in url:
                if "/insights" in url:
                    resp.json.return_value = {
                        "data": [{"spend": "10.50", "impressions": "5000", "clicks": "200"}]
                    }
                elif "/campaigns" in url:
                    resp.json.return_value = {
                        "data": [{"id": "camp_1", "name": "Test", "status": "ACTIVE", "daily_budget": "2500", "objective": "LINK_CLICKS"}]
                    }
                else:
                    resp.json.return_value = {"data": []}
            elif "business-api.tiktok.com" in url:
                resp.json.return_value = {
                    "code": 0,
                    "data": {"list": [{"metrics": {"spend": "5.00", "impressions": "2000", "clicks": "80"}}]},
                }
            elif "myshopify.com" in url:
                resp.json.return_value = {"orders": [], "products": []}
            elif "klaviyo.com" in url:
                resp.json.return_value = {"data": []}
            else:
                resp.json.return_value = {}
            return resp

        def _generic_post(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"success": True, "id": "new_123"}
            resp.text = '{"success": true}'
            return resp

        def _generic_delete(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"success": True}
            return resp

        mock_get.side_effect = _generic_get
        mock_post.side_effect = _generic_post
        mock_delete.side_effect = _generic_delete
        yield {"get": mock_get, "post": mock_post, "delete": mock_delete}
