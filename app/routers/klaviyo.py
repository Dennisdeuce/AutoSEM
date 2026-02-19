"""
Klaviyo router - Email Marketing + Abandoned Cart Flows
Uses Klaviyo REST API (revision 2024-10-15).
"""

import os
import logging

import requests
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, ActivityLogModel

logger = logging.getLogger("AutoSEM.Klaviyo")
router = APIRouter()

KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY", "")
KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_REVISION = "2024-10-15"


def _klaviyo_headers():
    return {
        "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
        "revision": KLAVIYO_REVISION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _klaviyo_request(method: str, path: str, payload: dict = None):
    """Make an authenticated request to Klaviyo API."""
    url = f"{KLAVIYO_BASE_URL}/{path.lstrip('/')}"
    resp = requests.request(
        method,
        url,
        headers=_klaviyo_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _log_activity(db: Session, action: str, entity_id: str = None, details: str = None):
    """Log an activity entry."""
    try:
        log = ActivityLogModel(
            action=action,
            entity_type="email_flow",
            entity_id=entity_id or "",
            details=details or "",
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ─── Request Models ──────────────────────────────────────────────

class TriggerEventRequest(BaseModel):
    event_name: str
    email: str
    properties: Optional[dict] = None


# ─── Endpoints ───────────────────────────────────────────────────

@router.get("/status", summary="Check Klaviyo status",
            description="Validate API key by fetching account info")
def klaviyo_status():
    if not KLAVIYO_API_KEY:
        return {
            "status": "not_configured",
            "connected": False,
            "message": "KLAVIYO_API_KEY not set",
        }

    try:
        data = _klaviyo_request("GET", "/accounts/")
        accounts = data.get("data", [])
        if accounts:
            account = accounts[0]
            attrs = account.get("attributes", {})
            return {
                "status": "ok",
                "connected": True,
                "account_name": attrs.get("contact_information", {}).get("organization_name", ""),
                "public_api_key": attrs.get("contact_information", {}).get("default_sender_email", ""),
            }
        return {"status": "ok", "connected": True, "message": "API key valid"}
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return {"status": "error", "connected": False, "message": "Invalid API key"}
        return {"status": "error", "connected": False, "message": str(e)}
    except Exception as e:
        return {"status": "error", "connected": False, "message": str(e)}


@router.get("/flows", summary="List all flows",
            description="Get all Klaviyo flows (abandoned cart, welcome, etc.)")
def list_flows():
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        data = _klaviyo_request("GET", "/flows/")
        flows = data.get("data", [])
        return {
            "status": "ok",
            "count": len(flows),
            "flows": [
                {
                    "id": f.get("id"),
                    "name": f.get("attributes", {}).get("name"),
                    "status": f.get("attributes", {}).get("status"),
                    "trigger_type": f.get("attributes", {}).get("trigger_type"),
                    "created": f.get("attributes", {}).get("created"),
                    "updated": f.get("attributes", {}).get("updated"),
                }
                for f in flows
            ],
        }
    except Exception as e:
        logger.error(f"Failed to list flows: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/flows/{flow_id}", summary="Get flow details",
            description="Get details and action steps for a specific flow")
def get_flow(flow_id: str):
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        data = _klaviyo_request("GET", f"/flows/{flow_id}/?include=flow-actions")
        flow = data.get("data", {})
        included = data.get("included", [])
        actions = [
            {
                "id": a.get("id"),
                "type": a.get("attributes", {}).get("action_type"),
                "status": a.get("attributes", {}).get("status"),
                "settings": a.get("attributes", {}).get("settings"),
            }
            for a in included
            if a.get("type") == "flow-action"
        ]
        return {
            "status": "ok",
            "flow": {
                "id": flow.get("id"),
                "name": flow.get("attributes", {}).get("name"),
                "status": flow.get("attributes", {}).get("status"),
                "trigger_type": flow.get("attributes", {}).get("trigger_type"),
            },
            "actions": actions,
        }
    except Exception as e:
        logger.error(f"Failed to get flow {flow_id}: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/metrics", summary="Get email performance metrics",
            description="Get email metrics (open rate, click rate, revenue)")
def get_metrics():
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        data = _klaviyo_request("GET", "/metrics/")
        metrics = data.get("data", [])
        return {
            "status": "ok",
            "count": len(metrics),
            "metrics": [
                {
                    "id": m.get("id"),
                    "name": m.get("attributes", {}).get("name"),
                    "integration": m.get("attributes", {}).get("integration", {}).get("name"),
                }
                for m in metrics
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/profiles", summary="List recent profiles",
            description="Get recent profiles/subscribers from Klaviyo")
def list_profiles(page_size: int = Query(20, ge=1, le=100)):
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        data = _klaviyo_request("GET", f"/profiles/?page[size]={page_size}")
        profiles = data.get("data", [])
        return {
            "status": "ok",
            "count": len(profiles),
            "profiles": [
                {
                    "id": p.get("id"),
                    "email": p.get("attributes", {}).get("email"),
                    "first_name": p.get("attributes", {}).get("first_name"),
                    "last_name": p.get("attributes", {}).get("last_name"),
                    "created": p.get("attributes", {}).get("created"),
                }
                for p in profiles
            ],
        }
    except Exception as e:
        logger.error(f"Failed to list profiles: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/create-abandoned-cart-flow", summary="Create abandoned cart flow",
             description="Create the 3-email abandoned cart sequence per AutoSEM spec")
def create_abandoned_cart_flow(db: Session = Depends(get_db)):
    """
    Creates a 3-email abandoned cart flow:
      1. 1 hour:  "Did you forget something?" - cart items + product images
      2. 24 hours: "Still thinking it over?" - social proof + reviews
      3. 48 hours: "Last chance - here's 10% off" - discount code
    """
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        # Step 1: Create the flow with a metric trigger for "Checkout Started"
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

        flow_resp = _klaviyo_request("POST", "/flows/", flow_payload)
        flow_id = flow_resp.get("data", {}).get("id")

        if not flow_id:
            return {"status": "error", "message": "Failed to create flow - no ID returned"}

        # Step 2: Create the 3 email actions on the flow
        email_sequence = [
            {
                "delay_hours": 1,
                "subject": "Did you forget something?",
                "preview": "Your cart is waiting for you",
                "body_summary": "Cart items with product images, direct checkout link",
            },
            {
                "delay_hours": 24,
                "subject": "Still thinking it over?",
                "preview": "See what others are saying",
                "body_summary": "Social proof, customer reviews, best-seller badges",
            },
            {
                "delay_hours": 48,
                "subject": "Last chance - here's 10% off",
                "preview": "Your exclusive discount expires soon",
                "body_summary": "Discount code via Klaviyo coupon API, urgency messaging",
            },
        ]

        created_actions = []
        for i, email in enumerate(email_sequence):
            action_payload = {
                "data": {
                    "type": "flow-action",
                    "attributes": {
                        "action_type": "EMAIL",
                        "status": "draft",
                        "settings": {
                            "subject": email["subject"],
                            "preview_text": email["preview"],
                        },
                        "tracking_options": {
                            "is_tracking_opens": True,
                            "is_tracking_clicks": True,
                        },
                    },
                    "relationships": {
                        "flow": {
                            "data": {
                                "type": "flow",
                                "id": flow_id,
                            }
                        }
                    },
                }
            }

            try:
                action_resp = _klaviyo_request("POST", "/flow-actions/", action_payload)
                action_id = action_resp.get("data", {}).get("id")
                created_actions.append({
                    "step": i + 1,
                    "action_id": action_id,
                    "delay_hours": email["delay_hours"],
                    "subject": email["subject"],
                    "body_summary": email["body_summary"],
                })
            except Exception as e:
                logger.warning(f"Failed to create email step {i + 1}: {e}")
                created_actions.append({
                    "step": i + 1,
                    "error": str(e),
                    "subject": email["subject"],
                })

        _log_activity(db, "KLAVIYO_ABANDONED_CART_CREATED", flow_id,
                     f"3-email abandoned cart flow created ({len([a for a in created_actions if 'action_id' in a])} emails)")

        return {
            "status": "created",
            "flow_id": flow_id,
            "flow_name": "AutoSEM Abandoned Cart",
            "email_count": len([a for a in created_actions if "action_id" in a]),
            "actions": created_actions,
            "note": "Flow created in DRAFT status. Review email templates in Klaviyo UI before activating.",
        }

    except Exception as e:
        logger.error(f"Failed to create abandoned cart flow: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/trigger-event", summary="Trigger a custom event",
             description="Send a custom event (e.g., cart abandonment) to Klaviyo for flow triggers")
def trigger_event(req: TriggerEventRequest, db: Session = Depends(get_db)):
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        payload = {
            "data": {
                "type": "event",
                "attributes": {
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {
                                "name": req.event_name,
                            },
                        }
                    },
                    "profile": {
                        "data": {
                            "type": "profile",
                            "attributes": {
                                "email": req.email,
                            },
                        }
                    },
                    "properties": req.properties or {},
                },
            }
        }

        _klaviyo_request("POST", "/events/", payload)

        _log_activity(db, "KLAVIYO_EVENT_TRIGGERED", req.event_name,
                     f"Event '{req.event_name}' triggered for {req.email}")

        return {
            "status": "ok",
            "event_name": req.event_name,
            "email": req.email,
            "message": f"Event '{req.event_name}' sent to Klaviyo",
        }

    except Exception as e:
        logger.error(f"Failed to trigger event: {e}")
        return {"status": "error", "message": str(e)}
