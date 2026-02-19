"""
Shopify Webhook Registration Service
Registers order/create webhook with Shopify Admin API on app startup.
Ensures the webhook exists (idempotent — skips if already registered).
"""

import os
import logging
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("autosem.shopify_webhooks")

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")


def _get_token() -> str:
    """Get a fresh Shopify token via client_credentials grant."""
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        return ""
    try:
        resp = requests.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", "")
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
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    return resp.json()


def list_webhooks(token: str = None) -> List[Dict]:
    """List all registered webhooks."""
    token = token or _get_token()
    if not token:
        return []
    data = _shopify_api("GET", "webhooks.json", token)
    return data.get("webhooks", [])


def register_order_webhook(callback_url: str) -> Dict:
    """Register an orders/create webhook with Shopify.

    Idempotent: if a webhook for orders/create pointing at the same URL
    already exists, it is skipped.

    Args:
        callback_url: The full URL Shopify should POST to on order creation
                      (e.g. https://auto-sem.replit.app/api/v1/shopify/webhook/order-created)

    Returns:
        dict with registration result
    """
    token = _get_token()
    if not token:
        return {"status": "error", "message": "No Shopify token available"}

    # Check if webhook already exists
    existing = list_webhooks(token)
    for wh in existing:
        if wh.get("topic") == "orders/create" and wh.get("address") == callback_url:
            logger.info(f"Shopify orders/create webhook already registered: {callback_url}")
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

    try:
        data = _shopify_api("POST", "webhooks.json", token, json=payload)
        webhook = data.get("webhook")
        if webhook:
            logger.info(f"Registered Shopify orders/create webhook: {webhook.get('id')} -> {callback_url}")
            return {
                "status": "registered",
                "webhook_id": webhook.get("id"),
                "topic": webhook.get("topic"),
                "address": webhook.get("address"),
            }
        else:
            errors = data.get("errors", data)
            logger.error(f"Shopify webhook registration failed: {errors}")
            return {"status": "error", "message": str(errors)}
    except Exception as e:
        logger.error(f"Shopify webhook registration exception: {e}")
        return {"status": "error", "message": str(e)}


def register_webhooks_on_startup():
    """Called from main.py on app startup to ensure webhooks are registered."""
    base_url = os.getenv("AUTOSEM_BASE_URL", "https://auto-sem.replit.app")
    callback_url = f"{base_url}/api/v1/shopify/webhook/order-created"

    logger.info(f"Registering Shopify webhooks (callback: {callback_url})")
    result = register_order_webhook(callback_url)
    logger.info(f"Shopify webhook registration result: {result.get('status')}")
    return result
