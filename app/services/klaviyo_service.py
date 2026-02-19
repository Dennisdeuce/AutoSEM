"""
Klaviyo Service — Abandoned Cart Flows + Email Marketing
Uses Klaviyo REST API revision 2024-10-15.
Generates Shopify discount codes for the 48-hour email via Shopify Admin API.
"""

import os
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("autosem.klaviyo_service")

KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY", "")
KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_REVISION = "2024-10-15"

# Shopify config for discount code generation
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")


class KlaviyoService:
    """Manages Klaviyo flows, events, and abandoned cart sequences."""

    # 3-email abandoned cart sequence per CLAUDE.md spec
    ABANDONED_CART_EMAILS = [
        {
            "delay_seconds": 3600,  # 1 hour
            "subject": "Did you forget something?",
            "preview_text": "Your cart is waiting for you",
            "body_summary": "Cart items with product images, direct checkout link",
            "template_name": "AutoSEM Cart Reminder 1",
        },
        {
            "delay_seconds": 86400,  # 24 hours
            "subject": "Still thinking it over?",
            "preview_text": "See what others are saying",
            "body_summary": "Social proof, customer reviews, best-seller badges",
            "template_name": "AutoSEM Cart Reminder 2",
        },
        {
            "delay_seconds": 172800,  # 48 hours
            "subject": "Last chance — here's 10% off",
            "preview_text": "Your exclusive discount expires soon",
            "body_summary": "Discount code via Shopify, urgency messaging",
            "template_name": "AutoSEM Cart Reminder 3 — Discount",
        },
    ]

    def __init__(self):
        self.api_key = KLAVIYO_API_KEY

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Klaviyo-API-Key {self.api_key}",
            "revision": KLAVIYO_REVISION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, payload: dict = None) -> Dict:
        """Make an authenticated Klaviyo API request."""
        url = f"{KLAVIYO_BASE_URL}/{path.lstrip('/')}"
        resp = requests.request(
            method, url,
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ─── Core Methods ────────────────────────────────────────────

    def create_abandoned_cart_flow(self) -> Dict:
        """Create the full 3-email abandoned cart flow in Klaviyo.

        1. Creates a flow triggered by 'Checkout Started' metric
        2. Adds 3 email actions with time delays
        3. Generates a Shopify discount code for the 48-hour email
        """
        if not self.is_configured:
            return {"success": False, "error": "KLAVIYO_API_KEY not set"}

        # Step 1: Create the flow
        flow_payload = {
            "data": {
                "type": "flow",
                "attributes": {
                    "name": "AutoSEM Abandoned Cart",
                    "status": "draft",
                    "trigger_type": "metric",
                },
            }
        }
        flow_resp = self._request("POST", "/flows/", flow_payload)
        flow_id = flow_resp.get("data", {}).get("id")

        if not flow_id:
            return {"success": False, "error": "Flow creation returned no ID"}

        # Step 2: Generate Shopify discount code for email 3
        discount_code = self._create_shopify_discount()

        # Step 3: Create the 3 email actions
        actions_created = []
        for i, email in enumerate(self.ABANDONED_CART_EMAILS):
            settings = {
                "subject": email["subject"],
                "preview_text": email["preview_text"],
            }
            # Inject discount code into email 3 settings
            if i == 2 and discount_code:
                settings["discount_code"] = discount_code

            action_payload = {
                "data": {
                    "type": "flow-action",
                    "attributes": {
                        "action_type": "EMAIL",
                        "status": "draft",
                        "settings": settings,
                        "tracking_options": {
                            "is_tracking_opens": True,
                            "is_tracking_clicks": True,
                        },
                    },
                    "relationships": {
                        "flow": {
                            "data": {"type": "flow", "id": flow_id}
                        }
                    },
                }
            }

            try:
                action_resp = self._request("POST", "/flow-actions/", action_payload)
                action_id = action_resp.get("data", {}).get("id")
                actions_created.append({
                    "step": i + 1,
                    "action_id": action_id,
                    "delay_seconds": email["delay_seconds"],
                    "subject": email["subject"],
                    "body_summary": email["body_summary"],
                })
            except Exception as e:
                logger.warning(f"Failed to create email step {i + 1}: {e}")
                actions_created.append({
                    "step": i + 1,
                    "error": str(e),
                    "subject": email["subject"],
                })

        successful = [a for a in actions_created if "action_id" in a]

        return {
            "success": True,
            "flow_id": flow_id,
            "flow_name": "AutoSEM Abandoned Cart",
            "emails_created": len(successful),
            "discount_code": discount_code,
            "actions": actions_created,
            "note": "Flow created in DRAFT status. Review templates in Klaviyo UI before activating.",
        }

    def trigger_flow(self, event_name: str, email: str,
                     properties: Optional[Dict] = None) -> Dict:
        """Send a custom event to Klaviyo to trigger a flow.

        Common events: 'Checkout Started', 'Added to Cart', 'Order Placed'
        """
        if not self.is_configured:
            return {"success": False, "error": "KLAVIYO_API_KEY not set"}

        payload = {
            "data": {
                "type": "event",
                "attributes": {
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {"name": event_name},
                        }
                    },
                    "profile": {
                        "data": {
                            "type": "profile",
                            "attributes": {"email": email},
                        }
                    },
                    "properties": properties or {},
                },
            }
        }

        self._request("POST", "/events/", payload)
        return {
            "success": True,
            "event_name": event_name,
            "email": email,
        }

    def get_flow_metrics(self) -> Dict:
        """Get performance metrics for all flows (opens, clicks, revenue)."""
        if not self.is_configured:
            return {"success": False, "error": "KLAVIYO_API_KEY not set"}

        # Get all flows
        flows_resp = self._request("GET", "/flows/")
        flows = flows_resp.get("data", [])

        # Get email-related metrics
        metrics_resp = self._request("GET", "/metrics/")
        metrics = metrics_resp.get("data", [])

        # Summarize
        email_metrics = [
            m for m in metrics
            if "email" in (m.get("attributes", {}).get("integration", {}).get("name", "") or "").lower()
        ]

        flow_summary = []
        for f in flows:
            attrs = f.get("attributes", {})
            flow_summary.append({
                "id": f.get("id"),
                "name": attrs.get("name"),
                "status": attrs.get("status"),
                "trigger_type": attrs.get("trigger_type"),
                "created": attrs.get("created"),
                "updated": attrs.get("updated"),
            })

        return {
            "success": True,
            "flow_count": len(flows),
            "flows": flow_summary,
            "email_metric_count": len(email_metrics),
            "metrics": [
                {
                    "id": m.get("id"),
                    "name": m.get("attributes", {}).get("name"),
                }
                for m in email_metrics[:20]
            ],
        }

    # ─── Shopify Discount ────────────────────────────────────────

    def _create_shopify_discount(self) -> Optional[str]:
        """Create a 10% discount code on Shopify for the abandoned cart email."""
        if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
            logger.info("Shopify credentials not set — skipping discount code generation")
            return None

        try:
            # Get a fresh Shopify token
            token_resp = requests.post(
                f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": SHOPIFY_CLIENT_ID,
                    "client_secret": SHOPIFY_CLIENT_SECRET,
                },
                timeout=15,
            )
            token_resp.raise_for_status()
            shopify_token = token_resp.json().get("access_token", "")

            if not shopify_token:
                return None

            # Create a price rule for 10% off
            import random
            code = f"COMEBACK10-{random.randint(1000, 9999)}"

            price_rule_payload = {
                "price_rule": {
                    "title": code,
                    "target_type": "line_item",
                    "target_selection": "all",
                    "allocation_method": "across",
                    "value_type": "percentage",
                    "value": "-10.0",
                    "customer_selection": "all",
                    "usage_limit": 100,
                    "starts_at": "2026-01-01T00:00:00Z",
                }
            }

            api_version = os.environ.get("SHOPIFY_API_VERSION", "2024-10")
            headers = {
                "X-Shopify-Access-Token": shopify_token,
                "Content-Type": "application/json",
            }

            rule_resp = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/{api_version}/price_rules.json",
                headers=headers,
                json=price_rule_payload,
                timeout=15,
            )
            rule_resp.raise_for_status()
            rule_id = rule_resp.json().get("price_rule", {}).get("id")

            if not rule_id:
                return None

            # Create the discount code on the price rule
            code_payload = {
                "discount_code": {"code": code}
            }
            code_resp = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/{api_version}/price_rules/{rule_id}/discount_codes.json",
                headers=headers,
                json=code_payload,
                timeout=15,
            )
            code_resp.raise_for_status()

            logger.info(f"Created Shopify discount code: {code}")
            return code

        except Exception as e:
            logger.warning(f"Failed to create Shopify discount code: {e}")
            return None
