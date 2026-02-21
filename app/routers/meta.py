"""
Meta Ads router - OAuth + Campaign Management + Ad Creative CRUD
v2.1.0 - Added ad-level query endpoints and creative creation/update/delete
"""

import os
import json
import logging
import time
from typing import Optional

import requests
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, MetaTokenModel, ActivityLogModel

logger = logging.getLogger("AutoSEM.Meta")
router = APIRouter()

META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_REDIRECT_URI = os.environ.get("META_REDIRECT_URI", "https://auto-sem.replit.app/api/v1/meta/callback")
META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
META_GRAPH_BASE = "https://graph.facebook.com/v19.0"


def _get_active_token(db: Session) -> str:
    """Get the active Meta access token from DB or environment."""
    token_record = db.query(MetaTokenModel).first()
    if token_record and token_record.access_token:
        return token_record.access_token
    return os.environ.get("META_ACCESS_TOKEN", "")


def _appsecret_proof(token: str) -> str:
    """Generate appsecret_proof for Meta API calls."""
    import hashlib
    import hmac
    if not META_APP_SECRET:
        return ""
    return hmac.new(
        META_APP_SECRET.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _log_activity(db: Session, action: str, entity_id: str = None, details: str = None):
    """Log an activity entry."""
    try:
        log = ActivityLogModel(
            action=action,
            entity_type="campaign",
            entity_id=entity_id or "",
            details=details or "",
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ─── OAuth Endpoints ──────────────────────────────────────────────

@router.get("/connect", summary="Connect Meta",
            description="Redirect to Meta OAuth authorization")
def connect_meta():
    if not META_APP_ID:
        return {"error": "META_APP_ID not configured"}

    auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_REDIRECT_URI}"
        f"&scope=ads_management,ads_read,business_management"
        f"&response_type=code"
    )
    return RedirectResponse(url=auth_url)


@router.get("/callback", summary="OAuth Callback",
            description="Handle Meta OAuth callback")
def oauth_callback(
    code: str = Query(None),
    error: str = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return HTMLResponse(content=f"<h1>Error</h1><p>{error}</p>")

    if not code:
        return HTMLResponse(content="<h1>Error</h1><p>No auth code received</p>")

    try:
        token_url = (
            f"{META_GRAPH_BASE}/oauth/access_token"
            f"?client_id={META_APP_ID}"
            f"&redirect_uri={META_REDIRECT_URI}"
            f"&client_secret={META_APP_SECRET}"
            f"&code={code}"
        )
        resp = requests.get(token_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        short_token = data.get("access_token")
        if not short_token:
            return HTMLResponse(content="<h1>Error</h1><p>No token received</p>")

        long_url = (
            f"{META_GRAPH_BASE}/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={META_APP_ID}"
            f"&client_secret={META_APP_SECRET}"
            f"&fb_exchange_token={short_token}"
        )
        long_resp = requests.get(long_url, timeout=30)
        long_resp.raise_for_status()
        long_data = long_resp.json()

        long_token = long_data.get("access_token", short_token)

        existing = db.query(MetaTokenModel).first()
        if existing:
            existing.access_token = long_token
            existing.token_type = "long_lived"
        else:
            token_record = MetaTokenModel(
                access_token=long_token,
                token_type="long_lived",
            )
            db.add(token_record)
        db.commit()

        logger.info("Meta OAuth token saved successfully")
        success_html = "<h1>Meta Connected!</h1><p>Long-lived token saved. You can close this window.</p><script>setTimeout(() => window.close(), 3000)</script>"
        return HTMLResponse(content=success_html)

    except Exception as e:
        logger.error(f"Meta OAuth failed: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")


@router.get("/status", summary="Check Meta Status",
            description="Check current Meta token status")
def check_meta_status(db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"connected": False, "message": "No Meta token found"}

    try:
        debug_resp = requests.get(
            f"{META_GRAPH_BASE}/debug_token"
            f"?input_token={access_token}"
            f"&access_token={META_APP_ID}|{META_APP_SECRET}",
            timeout=10,
        )
        debug_data = debug_resp.json().get("data", {}) if debug_resp.status_code == 200 else {}

        days_remaining = None
        expires_at = debug_data.get("expires_at", 0)
        if expires_at:
            remaining_seconds = expires_at - time.time()
            days_remaining = max(0, int(remaining_seconds / 86400))

        scopes = debug_data.get("scopes", [])
        is_valid = debug_data.get("is_valid", False)

        if is_valid:
            message = f"Token valid for {days_remaining} more days" if days_remaining else "Token valid"
            return {
                "connected": True,
                "status": "healthy",
                "days_remaining": days_remaining,
                "scopes": scopes,
                "message": message,
                "refresh_url": None,
            }
        else:
            return {"connected": False, "message": "Token expired or invalid"}

    except Exception as e:
        try:
            resp = requests.get(
                f"{META_GRAPH_BASE}/me?access_token={access_token}",
                timeout=10,
            )
            if resp.status_code == 200:
                return {"connected": True, "status": "healthy", "message": "Token valid"}
            return {"connected": False, "message": "Token expired or invalid"}
        except Exception as e2:
            return {"connected": False, "message": str(e2)}


@router.post("/refresh", summary="Refresh Meta Token",
             description="Refresh the current Meta access token")
def refresh_meta_token(db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No token to refresh"}

    try:
        url = (
            f"{META_GRAPH_BASE}/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={META_APP_ID}"
            f"&client_secret={META_APP_SECRET}"
            f"&fb_exchange_token={access_token}"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        new_token = data.get("access_token")
        if new_token:
            token_record = db.query(MetaTokenModel).first()
            if token_record:
                token_record.access_token = new_token
            else:
                token_record = MetaTokenModel(
                    access_token=new_token,
                    token_type="long_lived",
                )
                db.add(token_record)
            db.commit()
            return {"status": "refreshed"}

        return {"status": "error", "message": "No token in response"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Campaign Management Endpoints ───────────────────────────────

class CampaignActionRequest(BaseModel):
    campaign_id: str


class SetBudgetRequest(BaseModel):
    campaign_id: str
    daily_budget_cents: int  # Budget in cents (e.g., 1500 = $15.00)


@router.post("/activate-campaign", summary="Activate a Meta campaign",
             description="Set a campaign status to ACTIVE via Meta Graph API")
def activate_campaign(req: CampaignActionRequest, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        resp = requests.post(
            f"{META_GRAPH_BASE}/{req.campaign_id}",
            data={
                "status": "ACTIVE",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        result = resp.json()

        if resp.status_code == 200 and result.get("success"):
            _log_activity(db, "META_CAMPAIGN_ACTIVATED", req.campaign_id,
                         f"Campaign {req.campaign_id} activated via API")
            logger.info(f"Meta campaign {req.campaign_id} activated")
            return {
                "status": "activated",
                "campaign_id": req.campaign_id,
                "meta_response": result,
            }
        else:
            error_msg = result.get("error", {}).get("message", str(result))
            logger.error(f"Failed to activate campaign: {error_msg}")
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": error_msg,
                "meta_response": result,
            }

    except Exception as e:
        logger.error(f"Exception activating campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/pause-campaign", summary="Pause a Meta campaign",
             description="Set a campaign status to PAUSED via Meta Graph API")
def pause_campaign(req: CampaignActionRequest, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        resp = requests.post(
            f"{META_GRAPH_BASE}/{req.campaign_id}",
            data={
                "status": "PAUSED",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        result = resp.json()

        if resp.status_code == 200 and result.get("success"):
            _log_activity(db, "META_CAMPAIGN_PAUSED", req.campaign_id,
                         f"Campaign {req.campaign_id} paused via API")
            logger.info(f"Meta campaign {req.campaign_id} paused")
            return {
                "status": "paused",
                "campaign_id": req.campaign_id,
                "meta_response": result,
            }
        else:
            error_msg = result.get("error", {}).get("message", str(result))
            logger.error(f"Failed to pause campaign: {error_msg}")
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": error_msg,
                "meta_response": result,
            }

    except Exception as e:
        logger.error(f"Exception pausing campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/set-budget", summary="Set campaign daily budget",
             description="Update daily budget. Tries campaign-level first (CBO), then adset-level. Budget in cents (1500 = $15.00)")
def set_campaign_budget(req: SetBudgetRequest, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    budget_dollars = req.daily_budget_cents / 100

    try:
        # ── Step 1: Try campaign-level budget update (CBO campaigns) ──
        campaign_resp = requests.post(
            f"{META_GRAPH_BASE}/{req.campaign_id}",
            data={
                "daily_budget": req.daily_budget_cents,
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        campaign_result = campaign_resp.json()

        if campaign_resp.status_code == 200 and campaign_result.get("success"):
            _log_activity(db, "META_BUDGET_SET", req.campaign_id,
                         f"Campaign budget set to ${budget_dollars:.2f}/day ({req.daily_budget_cents} cents) — campaign level (CBO)")
            logger.info(f"Campaign {req.campaign_id} budget set to ${budget_dollars:.2f}/day (campaign-level CBO)")
            return {
                "status": "updated",
                "level": "campaign",
                "campaign_id": req.campaign_id,
                "budget_cents": req.daily_budget_cents,
                "budget_dollars": budget_dollars,
                "message": f"Campaign-level budget set to ${budget_dollars:.2f}/day",
            }

        # ── Step 2: Campaign-level failed — try adset-level ──
        campaign_error = campaign_result.get("error", {}).get("message", "")
        logger.info(f"Campaign-level budget update failed ({campaign_error}), trying adset-level...")

        adsets_resp = requests.get(
            f"{META_GRAPH_BASE}/{req.campaign_id}/adsets",
            params={
                "fields": "id,name,daily_budget,status",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        adsets_data = adsets_resp.json().get("data", [])

        if not adsets_data:
            return {
                "status": "error",
                "campaign_id": req.campaign_id,
                "message": f"Campaign-level update failed ({campaign_error}) and no ad sets found",
            }

        updated = []
        errors = []
        for adset in adsets_data:
            adset_id = adset["id"]
            update_resp = requests.post(
                f"{META_GRAPH_BASE}/{adset_id}",
                data={
                    "daily_budget": req.daily_budget_cents,
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            result = update_resp.json()
            if update_resp.status_code == 200 and result.get("success"):
                updated.append({"adset_id": adset_id, "name": adset.get("name", ""), "new_budget_cents": req.daily_budget_cents})
            else:
                error_msg = result.get("error", {}).get("message", str(result))
                errors.append({"adset_id": adset_id, "error": error_msg})

        if updated:
            _log_activity(db, "META_BUDGET_SET", req.campaign_id,
                         f"Budget set to ${budget_dollars:.2f}/day ({req.daily_budget_cents} cents) on {len(updated)} ad sets")

        return {
            "status": "updated" if updated else "error",
            "level": "adset",
            "campaign_id": req.campaign_id,
            "budget_cents": req.daily_budget_cents,
            "budget_dollars": budget_dollars,
            "adsets_updated": updated,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Exception setting budget: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/campaigns", summary="List Meta campaigns",
            description="Get all campaigns from the Meta ad account with current status")
def list_meta_campaigns(db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    ad_account_id = META_AD_ACCOUNT_ID
    if not access_token or not ad_account_id:
        return {"status": "error", "message": "Meta not configured"}

    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/act_{ad_account_id}/campaigns",
            params={
                "fields": "id,name,status,daily_budget,lifetime_budget,objective",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "limit": 100,
            },
            timeout=15,
        )
        resp.raise_for_status()
        campaigns = resp.json().get("data", [])
        return {
            "status": "ok",
            "count": len(campaigns),
            "campaigns": campaigns,
        }

    except Exception as e:
        logger.error(f"Failed to list campaigns: {e}")
        return {"status": "error", "message": str(e)}


# ─── Ad-Level Query Endpoints (Phase 10B) ────────────────────────

@router.get("/campaigns/{campaign_id}/adsets", summary="List adsets for a campaign",
            description="Get all ad sets under a Meta campaign with targeting and budget info")
def list_campaign_adsets(campaign_id: str, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/{campaign_id}/adsets",
            params={
                "fields": "id,name,daily_budget,status,targeting,optimization_goal",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        resp.raise_for_status()
        adsets = resp.json().get("data", [])
        return {"status": "ok", "campaign_id": campaign_id, "adsets": adsets}
    except Exception as e:
        logger.error(f"Failed to list adsets for campaign {campaign_id}: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/adsets/{adset_id}/ads", summary="List ads for an adset",
            description="Get all ads under an adset with creative details")
def list_adset_ads(adset_id: str, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/{adset_id}/ads",
            params={
                "fields": "id,name,status,creative{id,name,title,body,image_url,thumbnail_url,video_id,call_to_action_type,object_story_spec}",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        resp.raise_for_status()
        ads = resp.json().get("data", [])
        return {"status": "ok", "adset_id": adset_id, "ads": ads}
    except Exception as e:
        logger.error(f"Failed to list ads for adset {adset_id}: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/campaigns/{campaign_id}/full-structure", summary="Full campaign structure",
            description="Get campaign → adsets → ads tree in one call")
def get_full_campaign_structure(campaign_id: str, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        # Get campaign info
        camp_resp = requests.get(
            f"{META_GRAPH_BASE}/{campaign_id}",
            params={
                "fields": "id,name,status,daily_budget,lifetime_budget,objective",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        camp_resp.raise_for_status()
        campaign_data = camp_resp.json()

        # Get adsets
        adsets_resp = requests.get(
            f"{META_GRAPH_BASE}/{campaign_id}/adsets",
            params={
                "fields": "id,name,daily_budget,status,targeting,optimization_goal",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        adsets_resp.raise_for_status()
        adsets = adsets_resp.json().get("data", [])

        # Get ads for each adset
        adset_tree = []
        for adset in adsets:
            ads_resp = requests.get(
                f"{META_GRAPH_BASE}/{adset['id']}/ads",
                params={
                    "fields": "id,name,status,creative{id,name,title,body,image_url,thumbnail_url,video_id,call_to_action_type,object_story_spec}",
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            ads_resp.raise_for_status()
            ads = ads_resp.json().get("data", [])
            adset_tree.append({"adset": adset, "ads": ads})

        return {
            "status": "ok",
            "campaign": campaign_data,
            "adsets": adset_tree,
        }
    except Exception as e:
        logger.error(f"Failed to get full structure for campaign {campaign_id}: {e}")
        return {"status": "error", "message": str(e)}


# ─── Ad Creative CRUD (Phase 10B) ────────────────────────────────

META_PAGE_ID = os.environ.get("META_PAGE_ID", "177394692123504")


class CreateAdRequest(BaseModel):
    adset_id: str
    name: str
    image_url: str = ""
    image_hash: Optional[str] = None
    primary_text: str
    headline: str
    description: str
    link: str
    cta: str = "SHOP_NOW"
    page_id: Optional[str] = None


class UpdateAdRequest(BaseModel):
    status: Optional[str] = None
    name: Optional[str] = None


@router.post("/create-ad", summary="Create a new ad with creative",
             description="Create an AdCreative + Ad under the specified adset")
def create_ad(req: CreateAdRequest, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    ad_account_id = META_AD_ACCOUNT_ID
    if not access_token or not ad_account_id:
        return {"status": "error", "message": "Meta not configured"}

    page_id = req.page_id or META_PAGE_ID
    if not page_id:
        return {"status": "error", "message": "META_PAGE_ID not configured. Pass page_id in request body."}

    try:
        # Step 1: Create AdCreative
        link_data = {
            "link": req.link,
            "message": req.primary_text,
            "name": req.headline,
            "description": req.description,
            "call_to_action": {"type": req.cta, "value": {"link": req.link}},
        }
        if req.image_hash:
            link_data["image_hash"] = req.image_hash
        elif req.image_url:
            link_data["picture"] = req.image_url
        object_story_spec = json.dumps({
            "page_id": page_id,
            "link_data": link_data,
        })

        creative_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{ad_account_id}/adcreatives",
            data={
                "name": f"Creative - {req.name}",
                "object_story_spec": object_story_spec,
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=30,
        )
        if creative_resp.status_code >= 400:
            error_body = creative_resp.json() if creative_resp.content else {}
            return {"status": "error", "message": f"Meta creative API error {creative_resp.status_code}",
                    "meta_error": error_body}
        creative_id = creative_resp.json().get("id")

        if not creative_id:
            return {"status": "error", "message": "Failed to create ad creative", "response": creative_resp.json()}

        # Step 2: Create Ad
        ad_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{ad_account_id}/ads",
            data={
                "name": req.name,
                "adset_id": req.adset_id,
                "creative": json.dumps({"creative_id": creative_id}),
                "status": "ACTIVE",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=30,
        )
        ad_resp.raise_for_status()
        ad_id = ad_resp.json().get("id")

        _log_activity(db, "META_AD_CREATED", ad_id,
                      f"Ad '{req.name}' created in adset {req.adset_id} with creative {creative_id}")

        return {
            "status": "created",
            "ad_id": ad_id,
            "creative_id": creative_id,
            "adset_id": req.adset_id,
        }

    except Exception as e:
        logger.error(f"Failed to create ad: {e}")
        return {"status": "error", "message": str(e)}


@router.put("/ads/{ad_id}/update", summary="Update an ad",
            description="Update ad status or name")
def update_ad(ad_id: str, req: UpdateAdRequest, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        update_data = {"access_token": access_token, "appsecret_proof": _appsecret_proof(access_token)}
        if req.status:
            update_data["status"] = req.status
        if req.name:
            update_data["name"] = req.name

        resp = requests.post(
            f"{META_GRAPH_BASE}/{ad_id}",
            data=update_data,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("success"):
            _log_activity(db, "META_AD_UPDATED", ad_id,
                          f"Ad {ad_id} updated: status={req.status}, name={req.name}")
            return {"status": "updated", "ad_id": ad_id}
        else:
            return {"status": "error", "ad_id": ad_id, "message": str(result)}

    except Exception as e:
        logger.error(f"Failed to update ad {ad_id}: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/ads/{ad_id}", summary="Delete an ad",
               description="Delete an underperforming ad")
def delete_ad(ad_id: str, db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    try:
        resp = requests.delete(
            f"{META_GRAPH_BASE}/{ad_id}",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("success"):
            _log_activity(db, "META_AD_DELETED", ad_id, f"Ad {ad_id} deleted")
            return {"status": "deleted", "ad_id": ad_id}
        else:
            return {"status": "error", "ad_id": ad_id, "message": str(result)}

    except Exception as e:
        logger.error(f"Failed to delete ad {ad_id}: {e}")
        return {"status": "error", "message": str(e)}
