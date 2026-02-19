"""
Klaviyo router - Email Marketing + Abandoned Cart Flows
Uses KlaviyoService for business logic. Revision 2024-10-15.
"""

import os
import logging

import requests
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, ActivityLogModel
from app.services.klaviyo_service import KlaviyoService

logger = logging.getLogger("AutoSEM.Klaviyo")
router = APIRouter()

KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY", "")
KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_REVISION = "2024-10-15"

service = KlaviyoService()


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
        method, url,
        headers=_klaviyo_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _log_activity(db: Session, action: str, entity_id: str = None, details: str = None):
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

class TriggerFlowRequest(BaseModel):
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
            description="Get flow metrics including opens, clicks, revenue")
def get_metrics():
    if not KLAVIYO_API_KEY:
        return {"status": "error", "message": "KLAVIYO_API_KEY not set"}

    try:
        result = service.get_flow_metrics()
        if result.get("success"):
            return {"status": "ok", **result}
        return {"status": "error", "message": result.get("error", "Unknown error")}
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
             description="Create the 3-email abandoned cart sequence with Shopify discount code")
def create_abandoned_cart_flow(db: Session = Depends(get_db)):
    try:
        result = service.create_abandoned_cart_flow()

        if result.get("success"):
            _log_activity(
                db, "KLAVIYO_ABANDONED_CART_CREATED",
                result.get("flow_id", ""),
                f"3-email flow created ({result.get('emails_created', 0)} emails, "
                f"discount: {result.get('discount_code', 'none')})",
            )
            return {"status": "created", **result}
        else:
            return {"status": "error", "message": result.get("error", "Unknown error")}

    except Exception as e:
        logger.error(f"Failed to create abandoned cart flow: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/trigger-flow", summary="Trigger a flow event",
             description="Send a custom event to Klaviyo to trigger a flow")
def trigger_flow(req: TriggerFlowRequest, db: Session = Depends(get_db)):
    try:
        result = service.trigger_flow(req.event_name, req.email, req.properties)

        if result.get("success"):
            _log_activity(
                db, "KLAVIYO_FLOW_TRIGGERED",
                req.event_name,
                f"Event '{req.event_name}' triggered for {req.email}",
            )
            return {"status": "ok", **result}
        else:
            return {"status": "error", "message": result.get("error", "Unknown error")}

    except Exception as e:
        logger.error(f"Failed to trigger flow: {e}")
        return {"status": "error", "message": str(e)}


# Keep legacy endpoint name for backwards compatibility
@router.post("/trigger-event", summary="Trigger a custom event (legacy)",
             description="Alias for /trigger-flow", include_in_schema=False)
def trigger_event(req: TriggerFlowRequest, db: Session = Depends(get_db)):
    return trigger_flow(req, db)
