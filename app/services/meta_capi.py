"""
Meta Conversions API (CAPI) Service
Server-side event tracking for reliable conversion attribution.

Meta recommends dual pixel+CAPI setup. Browser pixel can be blocked by
ad blockers, privacy settings, and iOS ATT. CAPI sends events server-side
directly from AutoSEM → Meta, guaranteeing delivery.

Reference: https://developers.facebook.com/docs/marketing-api/conversions-api
"""

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("autosem.meta_capi")

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"


class MetaCAPI:
    """Send server-side events to Meta Conversions API."""

    def __init__(self, pixel_id: str, access_token: str, app_secret: str = ""):
        self.pixel_id = pixel_id
        self.access_token = access_token
        self.app_secret = app_secret

    def _appsecret_proof(self) -> str:
        if not self.app_secret:
            return ""
        return hmac.new(
            self.app_secret.encode("utf-8"),
            self.access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _hash_pii(value: str) -> str:
        """SHA-256 hash a PII value per Meta requirements.

        Meta requires all user data fields (email, phone, name, etc.)
        to be lowercase-trimmed then SHA-256 hashed before sending.
        """
        if not value:
            return ""
        normalized = value.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def send_event(
        self,
        event_name: str,
        event_time: Optional[int] = None,
        event_source_url: str = "",
        event_id: str = "",
        user_data: Optional[Dict] = None,
        custom_data: Optional[Dict] = None,
        action_source: str = "website",
    ) -> Dict:
        """Send a single event to Meta Conversions API.

        Args:
            event_name: Purchase, AddToCart, InitiateCheckout, ViewContent, etc.
            event_time: Unix timestamp (defaults to now).
            event_source_url: The URL where the event occurred.
            event_id: Dedupe ID (match with browser pixel event_id).
            user_data: Hashed PII dict (em, ph, fn, ln, ct, st, zp, country).
            custom_data: Event-specific data (value, currency, content_ids, etc.).
            action_source: "website", "app", "email", "phone_call", etc.

        Returns:
            Meta API response dict.
        """
        if not self.pixel_id or not self.access_token:
            return {"error": "CAPI not configured (missing pixel_id or access_token)"}

        event = {
            "event_name": event_name,
            "event_time": event_time or int(time.time()),
            "action_source": action_source,
        }
        if event_source_url:
            event["event_source_url"] = event_source_url
        if event_id:
            event["event_id"] = event_id
        if user_data:
            event["user_data"] = user_data
        if custom_data:
            event["custom_data"] = custom_data

        payload = {
            "data": json.dumps([event]),
            "access_token": self.access_token,
        }
        proof = self._appsecret_proof()
        if proof:
            payload["appsecret_proof"] = proof

        url = f"{META_GRAPH_BASE}/{self.pixel_id}/events"

        try:
            resp = requests.post(url, data=payload, timeout=15)
            result = resp.json()

            if resp.status_code == 200:
                events_received = result.get("events_received", 0)
                logger.info(
                    f"CAPI {event_name}: sent to pixel {self.pixel_id}, "
                    f"events_received={events_received}"
                )
            else:
                logger.warning(
                    f"CAPI {event_name} error {resp.status_code}: {result}"
                )

            return result
        except Exception as e:
            logger.error(f"CAPI {event_name} request failed: {e}")
            return {"error": str(e)}

    def send_purchase(self, order: Dict) -> Dict:
        """Send a Purchase event from a Shopify order.

        Args:
            order: Raw Shopify order dict with total_price, customer,
                   line_items, landing_site, etc.
        """
        total_price = float(order.get("total_price", 0) or 0)
        currency = order.get("currency", "USD")
        customer = order.get("customer", {}) or {}
        line_items = order.get("line_items", []) or []
        order_id = order.get("id") or order.get("order_number") or ""
        landing_site = order.get("landing_site", "")

        # Build content_ids from line items
        content_ids = []
        contents = []
        for item in line_items:
            pid = str(item.get("product_id", ""))
            if pid:
                content_ids.append(pid)
                contents.append({
                    "id": pid,
                    "quantity": item.get("quantity", 1),
                    "item_price": float(item.get("price", 0) or 0),
                })

        # Hash customer PII
        user_data = {}
        email = customer.get("email", "")
        if email:
            user_data["em"] = [self._hash_pii(email)]
        first_name = customer.get("first_name", "")
        if first_name:
            user_data["fn"] = [self._hash_pii(first_name)]
        last_name = customer.get("last_name", "")
        if last_name:
            user_data["ln"] = [self._hash_pii(last_name)]
        phone = customer.get("phone", "")
        if phone:
            user_data["ph"] = [self._hash_pii(phone)]

        # Address data
        default_address = customer.get("default_address", {}) or {}
        city = default_address.get("city", "")
        if city:
            user_data["ct"] = [self._hash_pii(city)]
        state = default_address.get("province_code", "")
        if state:
            user_data["st"] = [self._hash_pii(state)]
        zip_code = default_address.get("zip", "")
        if zip_code:
            user_data["zp"] = [self._hash_pii(zip_code)]
        country = default_address.get("country_code", "")
        if country:
            user_data["country"] = [self._hash_pii(country)]

        # Build source URL
        event_source_url = ""
        if landing_site:
            if landing_site.startswith("http"):
                event_source_url = landing_site
            else:
                event_source_url = f"https://court-sportswear.com{landing_site}"

        custom_data = {
            "currency": currency,
            "value": total_price,
            "content_type": "product",
            "content_ids": content_ids,
            "contents": contents,
            "num_items": len(line_items),
            "order_id": str(order_id),
        }

        return self.send_event(
            event_name="Purchase",
            event_source_url=event_source_url,
            event_id=f"order_{order_id}",
            user_data=user_data,
            custom_data=custom_data,
        )

    def send_add_to_cart(self, product_data: Dict) -> Dict:
        """Send an AddToCart event.

        Args:
            product_data: Dict with product_id, product_name, price, currency,
                          and optional user_data (email, etc.).
        """
        custom_data = {
            "currency": product_data.get("currency", "USD"),
            "value": float(product_data.get("price", 0) or 0),
            "content_type": "product",
            "content_ids": [str(product_data.get("product_id", ""))],
            "content_name": product_data.get("product_name", ""),
        }

        user_data = {}
        email = product_data.get("email", "")
        if email:
            user_data["em"] = [self._hash_pii(email)]

        return self.send_event(
            event_name="AddToCart",
            event_source_url=product_data.get("source_url", "https://court-sportswear.com"),
            user_data=user_data if user_data else None,
            custom_data=custom_data,
        )

    def send_initiate_checkout(self, checkout_data: Dict) -> Dict:
        """Send an InitiateCheckout event.

        Args:
            checkout_data: Dict with value, currency, num_items,
                           and optional user_data.
        """
        custom_data = {
            "currency": checkout_data.get("currency", "USD"),
            "value": float(checkout_data.get("value", 0) or 0),
            "num_items": checkout_data.get("num_items", 0),
            "content_type": "product",
        }
        content_ids = checkout_data.get("content_ids", [])
        if content_ids:
            custom_data["content_ids"] = content_ids

        user_data = {}
        email = checkout_data.get("email", "")
        if email:
            user_data["em"] = [self._hash_pii(email)]

        return self.send_event(
            event_name="InitiateCheckout",
            event_source_url=checkout_data.get("source_url", "https://court-sportswear.com/checkout"),
            user_data=user_data if user_data else None,
            custom_data=custom_data,
        )


def get_capi_client(db_session) -> Optional[MetaCAPI]:
    """Factory: build a MetaCAPI client from DB/env credentials.

    Returns None if pixel_id or access_token are unavailable.
    """
    from app.database import MetaTokenModel

    # Get access token
    token_record = db_session.query(MetaTokenModel).first()
    access_token = ""
    if token_record and token_record.access_token:
        access_token = token_record.access_token
    else:
        access_token = os.environ.get("META_ACCESS_TOKEN", "")

    if not access_token:
        return None

    app_secret = os.environ.get("META_APP_SECRET", "")
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")

    # Get pixel ID from Meta API
    pixel_id = os.environ.get("META_PIXEL_ID", "")
    if not pixel_id and ad_account_id:
        try:
            proof = ""
            if app_secret:
                proof = hmac.new(
                    app_secret.encode("utf-8"),
                    access_token.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
            params = {
                "access_token": access_token,
                "fields": "id,name",
            }
            if proof:
                params["appsecret_proof"] = proof

            resp = requests.get(
                f"{META_GRAPH_BASE}/act_{ad_account_id}/adspixels",
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                pixels = resp.json().get("data", [])
                if pixels:
                    pixel_id = pixels[0]["id"]
                    logger.info(f"CAPI: resolved pixel_id={pixel_id} from ad account")
        except Exception as e:
            logger.warning(f"CAPI: failed to resolve pixel_id: {e}")

    if not pixel_id:
        return None

    return MetaCAPI(pixel_id=pixel_id, access_token=access_token, app_secret=app_secret)
