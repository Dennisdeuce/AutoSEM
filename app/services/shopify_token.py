"""
Shopify Token Auto-Refresh Service
Manages Shopify access tokens with auto-refresh before expiry.
Persists token + expiry to SettingsModel so all services share one token.
"""

import os
import time
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger("autosem.shopify_token")

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")

# In-memory cache (avoids DB read on every request)
_cache = {
    "access_token": "",
    "expires_at": 0.0,  # Unix timestamp
}


def _persist_token(token: str, expires_at: float):
    """Write token and expiry to SettingsModel."""
    try:
        from app.database import SessionLocal, SettingsModel
        db = SessionLocal()
        try:
            for key, value in [("shopify_access_token", token),
                               ("shopify_token_expires_at", str(expires_at))]:
                setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
                if setting:
                    setting.value = value
                else:
                    db.add(SettingsModel(key=key, value=value))
            db.commit()
            logger.info("Shopify token persisted to SettingsModel")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to persist Shopify token to DB: {e}")


def _load_from_db():
    """Load token + expiry from SettingsModel into in-memory cache."""
    try:
        from app.database import SessionLocal, SettingsModel
        db = SessionLocal()
        try:
            token_row = db.query(SettingsModel).filter(
                SettingsModel.key == "shopify_access_token"
            ).first()
            expires_row = db.query(SettingsModel).filter(
                SettingsModel.key == "shopify_token_expires_at"
            ).first()
            if token_row and token_row.value:
                _cache["access_token"] = token_row.value
                _cache["expires_at"] = float(expires_row.value) if expires_row and expires_row.value else 0.0
                logger.info(f"Loaded Shopify token from DB (expires_at={_cache['expires_at']:.0f})")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to load Shopify token from DB: {e}")


def refresh_shopify_token() -> str:
    """Fetch a new Shopify token via client_credentials grant.

    Persists to both in-memory cache and SettingsModel.
    Returns the new token string, or empty string on failure.
    """
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        logger.warning("Shopify client credentials not configured — cannot refresh")
        return ""

    try:
        url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
        logger.info(f"Refreshing Shopify token via {url}")
        resp = requests.post(
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        token = data.get("access_token", "")
        expires_in = data.get("expires_in", 86399)

        if not token:
            logger.error(f"Shopify token refresh returned no token: {data}")
            return ""

        # 5-minute safety buffer
        expires_at = time.time() + expires_in - 300

        # Update cache
        _cache["access_token"] = token
        _cache["expires_at"] = expires_at

        # Persist to DB
        _persist_token(token, expires_at)

        logger.info(f"Shopify token refreshed successfully (expires_in={expires_in}s)")
        return token

    except Exception as e:
        logger.error(f"Shopify token refresh failed: {e}")
        return ""


def get_shopify_token() -> str:
    """Get a valid Shopify token, refreshing if expired.

    All services that need a Shopify token should call this function
    instead of managing tokens independently.
    """
    # If cache is empty, try loading from DB
    if not _cache["access_token"]:
        _load_from_db()

    # If token is still valid, return it
    if _cache["access_token"] and time.time() < _cache["expires_at"]:
        return _cache["access_token"]

    # Token expired or missing — refresh
    return refresh_shopify_token()


def scheduled_token_refresh():
    """Called by the scheduler every 20 hours to proactively refresh."""
    logger.info("Scheduled Shopify token refresh triggered")
    token = refresh_shopify_token()
    if token:
        logger.info("Scheduled Shopify token refresh succeeded")
    else:
        logger.error("Scheduled Shopify token refresh FAILED")
