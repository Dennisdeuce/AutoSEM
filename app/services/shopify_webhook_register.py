"""
Shopify Webhook Registration Service
Registers order/create webhook with Shopify Admin API on app startup.
Ensures the webhook exists (idempotent — skips if already registered).
"""

import os
import logging
from typing import Dict, List

import requests

logger = logging.getLogger("autosem.shopify_webhooks")

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")


def _get_token() -> str:
    """Get a fresh Shopify token via client_credentials grant."""
    logger.info(f"Requesting Shopify token for store {SHOPIFY_STORE}")
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        logger.warning("SHOPIFY_CLIENT_ID or SHOPIFY_CLIENT_SECRET not set — cannot get token")
        return ""
    try:
        url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
        logger.info(f"POST {url} (grant_type=client_credentials)")
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
        logger.info(f"Token response status: {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            logger.info(f"Got Shopify token: {token[:12]}... (expires_in={data.get('expires_in', '?')}s)")
        else:
            logger.error(f"Token response had no access_token: {data}")
        return token
    except Exception as e:
        logger.error(f"Failed to get Shopify token for webhook registration: {e}")
        return ""


def _shopify_api(method: str, endpoint: str, token: str, **kwargs) -> dict:
    """Make an authenticated Shopify Admin API request."""
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    logger.info(f"Shopify API: {method} {url}")
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    logger.info(f"Shopify API response: {resp.status_code}")
    if resp.status_code >= 400:
        logger.error(f"Shopify API error body: {resp.text[:500]}")
    return resp.json()


def list_webhooks(token: str = None) -> List[Dict]:
    """List all registered webhooks."""
    token = token or _get_token()
    if not token:
        logger.warning("No token available — cannot list webhooks")
        return []
    data = _shopify_api("GET", "webhooks.json", token)
    webhooks = data.get("webhooks", [])
    logger.info(f"Found {len(webhooks)} existing webhooks")
    return webhooks


def register_order_webhook(callback_url: str) -> Dict:
    """Register an orders/create webhook with Shopify.

    Idempotent: if a webhook for orders/create pointing at the same URL
    already exists, it is skipped.
    """
    logger.info(f"Attempting to register orders/create webhook -> {callback_url}")

    token = _get_token()
    if not token:
        logger.error("Cannot register webhook: no Shopify token")
        return {"status": "error", "message": "No Shopify token available"}

    # Check if webhook already exists
    existing = list_webhooks(token)
    for wh in existing:
        if wh.get("topic") == "orders/create" and wh.get("address") == callback_url:
            logger.info(f"Webhook already registered (id={wh.get('id')}), skipping")
            return {
                "status": "already_registered",
                "webhook_id": wh.get("id"),
                "address": callback_url,
            }

    # Register new webhook
    payload = {
        "webhook": {
            "topic": "orders/create",
            "address": callback_url,
            "format": "json",
        }
    }
    logger.info(f"Registering new webhook with payload: {payload}")

    try:
        data = _shopify_api("POST", "webhooks.json", token, json=payload)
        webhook = data.get("webhook")
        if webhook:
            logger.info(f"Webhook registered successfully: id={webhook.get('id')}, topic={webhook.get('topic')}")
            return {
                "status": "registered",
                "webhook_id": webhook.get("id"),
                "topic": webhook.get("topic"),
                "address": webhook.get("address"),
            }
        else:
            errors = data.get("errors", data)
            logger.error(f"Shopify webhook registration failed. Response: {data}")
            return {"status": "error", "message": str(errors)}
    except Exception as e:
        logger.error(f"Shopify webhook registration exception: {e}")
        return {"status": "error", "message": str(e)}


def register_webhooks_on_startup():
    """Called from main.py on app startup to ensure webhooks are registered."""
    base_url = os.getenv("AUTOSEM_BASE_URL", "https://auto-sem.replit.app")
    callback_url = f"{base_url}/api/v1/shopify/webhook/order-created"

    logger.info(f"=== Shopify Webhook Registration (startup) ===")
    logger.info(f"SHOPIFY_STORE={SHOPIFY_STORE}")
    logger.info(f"SHOPIFY_CLIENT_ID={'set' if SHOPIFY_CLIENT_ID else 'NOT SET'}")
    logger.info(f"SHOPIFY_CLIENT_SECRET={'set' if SHOPIFY_CLIENT_SECRET else 'NOT SET'}")
    logger.info(f"Callback URL: {callback_url}")

    result = register_order_webhook(callback_url)
    logger.info(f"Webhook registration result: {result}")
    return result
