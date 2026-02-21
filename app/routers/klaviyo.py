"""
Klaviyo router - Email Marketing + Abandoned Cart Flows
Uses KlaviyoService for business logic. Revision 2024-10-15.
Phase 13: Removed hardcoded fallback key, added validate-key, diagnose,
          retry logic, health integration, status caching.
"""

import os
import time
import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, ActivityLogModel, SettingsModel
from app.services.klaviyo_service import KlaviyoService, _get_klaviyo_key, _klaviyo_diag

logger = logging.getLogger("AutoSEM.Klaviyo")


def _klaviyo_auto_init(db: Session = Depends(get_db)):
    """Router-level dependency: auto-init Klaviyo key from env to DB on every request."""
    _ensure_klaviyo_key_in_db(db)


router = APIRouter(dependencies=[Depends(_klaviyo_auto_init)])

KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_REVISION = "2024-10-15"

service = KlaviyoService()

# Status cache: avoid hammering Klaviyo /accounts on every call
_status_cache = {"data": None, "expires_at": 0.0}
STATUS_CACHE_TTL = 60  # seconds


def _ensure_klaviyo_key_in_db(db: Session):
    """Auto-init: if klaviyo_api_key is missing from DB, try env var only (no hardcoded keys)."""
    try:
        row = db.query(SettingsModel).filter(SettingsModel.key == "klaviyo_api_key").first()
        if row and row.value:
            return  # already in DB
        key = os.environ.get("KLAVIYO_API_KEY", "")
        if key:
            if row:
                row.value = key
            else:
                db.add(SettingsModel(key="klaviyo_api_key", value=key))
            db.commit()
            logger.info("Klaviyo auto-init: wrote API key to DB from env")
    except Exception as e:
        logger.warning(f"Klaviyo auto-init failed: {e}")


def _get_api_key() -> str:
    """Get the current Klaviyo API key (env or DB)."""
    return _get_klaviyo_key()


def _klaviyo_headers():
    return {
        "Authorization": f"Klaviyo-API-Key {_get_api_key()}",
        "revision": KLAVIYO_REVISION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _klaviyo_request(method: str, path: str, payload: dict = None):
    """Make an authenticated request to Klaviyo API with retry + exponential backoff (3 attempts)."""
    url = f"{KLAVIYO_BASE_URL}/{path.lstrip('/')}"
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.request(
                method, url,
                headers=_klaviyo_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            _klaviyo_diag["last_success_ts"] = time.time()
            return resp.json() if resp.content else {}
        except Exception as e:
            last_exc = e
            _klaviyo_diag["last_error_msg"] = str(e)
            if attempt < 2:
                wait = 2 ** attempt  # 1s, 2s
                time.sleep(wait)
    raise last_exc


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


class SetKeyRequest(BaseModel):
    api_key: str


class ValidateKeyRequest(BaseModel):
    api_key: str


# ─── Endpoints ───────────────────────────────────────────────────

@router.post("/set-key", summary="Set Klaviyo API key",
             description="Store Klaviyo API key in DB (survives restarts, no env var needed)")
def set_klaviyo_key(req: SetKeyRequest, db: Session = Depends(get_db)):
    try:
        row = db.query(SettingsModel).filter(SettingsModel.key == "klaviyo_api_key").first()
        if row:
            row.value = req.api_key
        else:
            row = SettingsModel(key="klaviyo_api_key", value=req.api_key)
            db.add(row)
        db.commit()

        # Reload the service instance so subsequent calls use the new key
        service.reload_key()

        # Quick validation — try to hit the accounts endpoint
        connected = False
        try:
            _klaviyo_request("GET", "/accounts/")
            connected = True
        except Exception:
            pass

        # Invalidate status cache
        _status_cache["expires_at"] = 0

        return {
            "status": "ok",
            "message": "Klaviyo API key saved",
            "connected": connected,
        }
    except Exception as e:
        logger.error(f"Failed to set Klaviyo key: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/validate-key", summary="Validate a Klaviyo API key",
             description="Test a key against Klaviyo accounts API. If valid, saves to DB.")
def validate_klaviyo_key(req: ValidateKeyRequest, db: Session = Depends(get_db)):
    """Test key against GET https://a.klaviyo.com/api/accounts/, save to DB if valid."""
    try:
        test_headers = {
            "Authorization": f"Klaviyo-API-Key {req.api_key}",
            "revision": KLAVIYO_REVISION,
            "Accept": "application/json",
        }
        resp = requests.get(
            f"{KLAVIYO_BASE_URL}/accounts/",
            headers=test_headers,
            timeout=15,
        )

        if resp.status_code == 401:
            return {"status": "error", "valid": False, "message": "Invalid API key — Klaviyo returned 401"}

        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("data", [])
        account_name = ""
        if accounts:
            account_name = accounts[0].get("attributes", {}).get("contact_information", {}).get("organization_name", "")

        # Key is valid — save to DB
        row = db.query(SettingsModel).filter(SettingsModel.key == "klaviyo_api_key").first()
        if row:
            row.value = req.api_key
        else:
            row = SettingsModel(key="klaviyo_api_key", value=req.api_key)
            db.add(row)
        db.commit()

        service.reload_key()
        _status_cache["expires_at"] = 0  # invalidate cache

        _log_activity(db, "KLAVIYO_KEY_VALIDATED", details=f"Key validated and saved. Account: {account_name}")

        return {
            "status": "ok",
            "valid": True,
            "message": "API key valid and saved to DB",
            "account_name": account_name,
        }
    except requests.exceptions.HTTPError as e:
        return {"status": "error", "valid": False, "message": f"Klaviyo API error: {e}"}
    except Exception as e:
        return {"status": "error", "valid": False, "message": str(e)}


@router.get("/diagnose", summary="Diagnose Klaviyo key status",
            description="Returns key source, masked prefix, last success time, last error")
def diagnose_klaviyo():
    key = _get_api_key()
    key_prefix = (key[:8] + "****") if key and len(key) > 8 else ("(empty)" if not key else key[:4] + "****")

    last_success = None
    if _klaviyo_diag.get("last_success_ts"):
        last_success = datetime.fromtimestamp(_klaviyo_diag["last_success_ts"], tz=timezone.utc).isoformat()

    return {
        "status": "ok",
        "key_source": _klaviyo_diag.get("last_key_source", "unknown"),
        "key_prefix": key_prefix,
        "key_present": bool(key),
        "last_successful_api_call": last_success,
        "last_error": _klaviyo_diag.get("last_error_msg"),
    }


@router.get("/status", summary="Check Klaviyo status",
            description="Validate API key by fetching account info (cached 60s)")
def klaviyo_status():
    # Return cached result if fresh
    now = time.time()
    if _status_cache["data"] is not None and now < _status_cache["expires_at"]:
        return _status_cache["data"]

    if not _get_api_key():
        result = {
            "status": "not_configured",
            "connected": False,
            "message": "KLAVIYO_API_KEY not set",
        }
        _status_cache["data"] = result
        _status_cache["expires_at"] = now + STATUS_CACHE_TTL
        return result

    try:
        data = _klaviyo_request("GET", "/accounts/")
        accounts = data.get("data", [])
        if accounts:
            account = accounts[0]
            attrs = account.get("attributes", {})
            result = {
                "status": "ok",
                "connected": True,
                "account_name": attrs.get("contact_information", {}).get("organization_name", ""),
                "public_api_key": attrs.get("contact_information", {}).get("default_sender_email", ""),
            }
        else:
            result = {"status": "ok", "connected": True, "message": "API key valid"}
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            result = {"status": "error", "connected": False, "message": "Invalid API key"}
        else:
            result = {"status": "error", "connected": False, "message": str(e)}
    except Exception as e:
        result = {"status": "error", "connected": False, "message": str(e)}

    _status_cache["data"] = result
    _status_cache["expires_at"] = now + STATUS_CACHE_TTL
    return result


@router.get("/flows", summary="List all flows",
            description="Get all Klaviyo flows (abandoned cart, welcome, etc.)")
def list_flows():
    if not _get_api_key():
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
    if not _get_api_key():
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
    if not _get_api_key():
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
    if not _get_api_key():
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
