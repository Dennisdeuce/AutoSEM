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


@router.get("/ad-images", summary="List ad account images",
            description="List images uploaded to the ad account with their hashes")
def list_ad_images(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}
    if not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "META_AD_ACCOUNT_ID not set"}

    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adimages",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "fields": "hash,name,url,url_128,created_time,status",
                "limit": limit,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return {"status": "ok", "count": len(data), "images": data}
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text if e.response else str(e)
        return {"status": "error", "message": error_body}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/upload-image", summary="Upload image to ad account by URL",
             description="Upload an image from URL to the ad account, returns image_hash")
def upload_ad_image(image_url: str = Query(...), name: str = Query("ad_image"), db: Session = Depends(get_db)):
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}
    if not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "META_AD_ACCOUNT_ID not set"}

    try:
        resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adimages",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            json={"url": image_url, "name": name},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        images = result.get("images", {})
        if images:
            img_data = list(images.values())[0]
            return {"status": "ok", "image_hash": img_data.get("hash"), "name": name, "data": img_data}
        return {"status": "ok", "result": result}
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text if e.response else str(e)
        return {"status": "error", "message": error_body}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Conversions API (CAPI) Endpoints ────────────────────────────

@router.post("/test-capi", summary="Send a test CAPI event",
             description="Send a test PageView event to verify Conversions API is working")
def test_capi(db: Session = Depends(get_db)):
    """Send a test event to Meta Conversions API and return the response."""
    from app.services.meta_capi import get_capi_client

    capi = get_capi_client(db)
    if not capi:
        return {
            "status": "error",
            "message": "CAPI not configured — missing pixel_id or Meta access token",
        }

    result = capi.send_event(
        event_name="PageView",
        event_source_url="https://court-sportswear.com",
        user_data={"client_user_agent": "AutoSEM-CAPI-Test/1.0"},
        custom_data={"test_event_code": "TEST_AUTOSEM"},
    )

    events_received = result.get("events_received", 0)
    success = events_received > 0

    _log_activity(db, "CAPI_TEST_SENT", capi.pixel_id,
                  f"Test event: events_received={events_received}, success={success}")

    return {
        "status": "ok" if success else "error",
        "pixel_id": capi.pixel_id,
        "events_received": events_received,
        "meta_response": result,
    }


@router.get("/capi-status", summary="Check CAPI configuration and recent events",
            description="Verify Conversions API is configured and check for recent server events")
def capi_status(db: Session = Depends(get_db)):
    """Check if CAPI is configured and fetch recent pixel event stats."""
    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "configured": False, "message": "No Meta token"}

    ad_account_id = META_AD_ACCOUNT_ID
    if not ad_account_id:
        return {"status": "error", "configured": False, "message": "No ad account ID"}

    # Find pixel(s)
    try:
        pixels_resp = requests.get(
            f"{META_GRAPH_BASE}/act_{ad_account_id}/adspixels",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "fields": "id,name,last_fired_time,is_created_by_business",
            },
            timeout=15,
        )
        pixels_resp.raise_for_status()
        pixels = pixels_resp.json().get("data", [])
    except Exception as e:
        return {"status": "error", "configured": False, "message": f"Pixel lookup failed: {e}"}

    if not pixels:
        return {"status": "error", "configured": False, "message": "No pixels found on ad account"}

    pixel_id = pixels[0]["id"]
    pixel_name = pixels[0].get("name", "")
    last_fired = pixels[0].get("last_fired_time")

    # Get recent event stats (last 24h)
    stats = []
    try:
        import time as _time
        stats_resp = requests.get(
            f"{META_GRAPH_BASE}/{pixel_id}/stats",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "aggregation": "event",
                "start_time": str(int(_time.time()) - 86400),
            },
            timeout=15,
        )
        if stats_resp.status_code == 200:
            stats = stats_resp.json().get("data", [])
    except Exception as e:
        logger.warning(f"CAPI stats fetch failed: {e}")

    return {
        "status": "ok",
        "configured": True,
        "pixel_id": pixel_id,
        "pixel_name": pixel_name,
        "last_fired": last_fired,
        "pixels_count": len(pixels),
        "recent_events_24h": stats,
        "all_pixels": [
            {"id": p.get("id"), "name": p.get("name"), "last_fired": p.get("last_fired_time")}
            for p in pixels
        ],
    }


# ─── Conversion Campaign & Objective Switching ───────────────────

class CreateConversionCampaignRequest(BaseModel):
    source_campaign_id: Optional[str] = None  # Copy targeting from this campaign
    name: str = "Court Sportswear - Sales - Conversion Optimized"
    daily_budget_cents: int = 1000  # $10/day default
    optimization_goal: str = "OFFSITE_CONVERSIONS"  # or "VALUE"
    pixel_id: Optional[str] = None  # Auto-detected if not provided
    status: str = "PAUSED"  # Start paused for review


class SwitchObjectiveRequest(BaseModel):
    campaign_id: str  # Old campaign to replace
    new_objective: str = "OUTCOME_SALES"  # New objective
    daily_budget_cents: Optional[int] = None  # None = keep same budget
    optimization_goal: str = "OFFSITE_CONVERSIONS"
    pause_old: bool = True  # Pause the old campaign after creating new one


def _resolve_pixel_id(access_token: str) -> Optional[str]:
    """Resolve the pixel ID from the ad account."""
    if not META_AD_ACCOUNT_ID:
        return None
    pixel_id = os.environ.get("META_PIXEL_ID", "")
    if pixel_id:
        return pixel_id
    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
            params={
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "fields": "id,name",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            pixels = resp.json().get("data", [])
            if pixels:
                return pixels[0]["id"]
    except Exception as e:
        logger.warning(f"Pixel ID resolution failed: {e}")
    return None


def _get_campaign_details(access_token: str, campaign_id: str) -> Optional[dict]:
    """Fetch full campaign details including adsets, ads, and targeting."""
    try:
        # Campaign info
        camp_resp = requests.get(
            f"{META_GRAPH_BASE}/{campaign_id}",
            params={
                "fields": "id,name,status,daily_budget,lifetime_budget,objective,special_ad_categories",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        camp_resp.raise_for_status()
        campaign = camp_resp.json()

        # Adsets with full targeting
        adsets_resp = requests.get(
            f"{META_GRAPH_BASE}/{campaign_id}/adsets",
            params={
                "fields": "id,name,daily_budget,status,targeting,optimization_goal,billing_event,bid_strategy,promoted_object",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        adsets_resp.raise_for_status()
        adsets = adsets_resp.json().get("data", [])

        # Ads with creatives for each adset
        for adset in adsets:
            ads_resp = requests.get(
                f"{META_GRAPH_BASE}/{adset['id']}/ads",
                params={
                    "fields": "id,name,status,creative{id}",
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            if ads_resp.status_code == 200:
                adset["_ads"] = ads_resp.json().get("data", [])
            else:
                adset["_ads"] = []

        campaign["_adsets"] = adsets
        return campaign
    except Exception as e:
        logger.error(f"Failed to get campaign details for {campaign_id}: {e}")
        return None


@router.post("/create-conversion-campaign",
             summary="Create a conversion-optimized campaign",
             description="Create a new campaign with OUTCOME_SALES objective and pixel tracking. "
                         "Copies targeting from an existing campaign if source_campaign_id is provided.")
def create_conversion_campaign(req: CreateConversionCampaignRequest, db: Session = Depends(get_db)):
    """Create a new campaign optimized for conversions (purchases).

    BUG-16 fix: The current active campaign uses LINK_CLICKS which optimizes
    for clicks, not purchases. This endpoint creates a proper conversion
    campaign with OUTCOME_SALES objective once the Meta Pixel is installed.
    """
    access_token = _get_active_token(db)
    if not access_token or not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "Meta not configured"}

    # Resolve pixel ID
    pixel_id = req.pixel_id or _resolve_pixel_id(access_token)
    if not pixel_id:
        return {
            "status": "error",
            "message": "No pixel found. Install Meta Pixel first via POST /api/v1/pixel/install, "
                       "or pass pixel_id in the request.",
        }

    # Get source campaign targeting if specified
    source_targeting = None
    source_adset = None
    source_ads = []
    if req.source_campaign_id:
        source = _get_campaign_details(access_token, req.source_campaign_id)
        if source and source.get("_adsets"):
            source_adset = source["_adsets"][0]  # Use first adset
            source_targeting = source_adset.get("targeting")
            source_ads = source_adset.get("_ads", [])

    try:
        # Step 1: Create Campaign with OUTCOME_SALES objective
        campaign_payload = {
            "name": req.name,
            "objective": "OUTCOME_SALES",
            "status": req.status,
            "special_ad_categories": "[]",
            "access_token": access_token,
            "appsecret_proof": _appsecret_proof(access_token),
        }

        camp_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/campaigns",
            data=campaign_payload,
            timeout=20,
        )
        camp_result = camp_resp.json()

        if camp_resp.status_code >= 400 or not camp_result.get("id"):
            error_msg = camp_result.get("error", {}).get("message", str(camp_result))
            return {"status": "error", "step": "create_campaign", "message": error_msg, "meta_response": camp_result}

        new_campaign_id = camp_result["id"]
        logger.info(f"Created conversion campaign {new_campaign_id}: {req.name}")

        # Step 2: Create Adset with conversion optimization
        adset_payload = {
            "campaign_id": new_campaign_id,
            "name": f"{req.name} - Adset",
            "optimization_goal": req.optimization_goal,
            "billing_event": "IMPRESSIONS",
            "daily_budget": str(req.daily_budget_cents),
            "status": req.status,
            "promoted_object": json.dumps({
                "pixel_id": pixel_id,
                "custom_event_type": "PURCHASE",
            }),
            "access_token": access_token,
            "appsecret_proof": _appsecret_proof(access_token),
        }

        # Copy targeting from source, or use broad defaults
        if source_targeting:
            adset_payload["targeting"] = json.dumps(source_targeting)
        else:
            adset_payload["targeting"] = json.dumps({
                "geo_locations": {"countries": ["US"]},
                "age_min": 25,
                "age_max": 65,
            })

        adset_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adsets",
            data=adset_payload,
            timeout=20,
        )
        adset_result = adset_resp.json()

        if adset_resp.status_code >= 400 or not adset_result.get("id"):
            error_msg = adset_result.get("error", {}).get("message", str(adset_result))
            return {
                "status": "partial",
                "step": "create_adset",
                "campaign_id": new_campaign_id,
                "message": f"Campaign created but adset failed: {error_msg}",
                "meta_response": adset_result,
            }

        new_adset_id = adset_result["id"]
        logger.info(f"Created conversion adset {new_adset_id}")

        # Step 3: Copy ads from source (if available)
        copied_ads = []
        for ad in source_ads:
            creative_id = ad.get("creative", {}).get("id")
            if not creative_id:
                continue
            ad_resp = requests.post(
                f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/ads",
                data={
                    "name": ad.get("name", "Copied Ad"),
                    "adset_id": new_adset_id,
                    "creative": json.dumps({"creative_id": creative_id}),
                    "status": req.status,
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=20,
            )
            if ad_resp.status_code == 200:
                copied_ads.append({
                    "ad_id": ad_resp.json().get("id"),
                    "name": ad.get("name"),
                    "creative_id": creative_id,
                })

        _log_activity(
            db, "META_CONVERSION_CAMPAIGN_CREATED", new_campaign_id,
            f"{req.name} | objective=OUTCOME_SALES | pixel={pixel_id} | "
            f"budget=${req.daily_budget_cents / 100:.2f}/day | "
            f"optimization={req.optimization_goal} | ads_copied={len(copied_ads)}",
        )

        budget_dollars = req.daily_budget_cents / 100
        return {
            "status": "created",
            "campaign_id": new_campaign_id,
            "adset_id": new_adset_id,
            "name": req.name,
            "objective": "OUTCOME_SALES",
            "optimization_goal": req.optimization_goal,
            "pixel_id": pixel_id,
            "daily_budget": f"${budget_dollars:.2f}",
            "initial_status": req.status,
            "ads_copied": copied_ads,
            "source_campaign_id": req.source_campaign_id,
            "next_steps": [
                f"Review campaign in Meta Ads Manager: https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={META_AD_ACCOUNT_ID}",
                "Add ad creatives if none were copied",
                f"Activate when ready: POST /api/v1/meta/activate-campaign with campaign_id={new_campaign_id}",
                "Monitor for 3-5 days to let Meta's algorithm learn",
                "Once profitable, increase budget via POST /api/v1/meta/set-budget",
            ],
        }

    except Exception as e:
        logger.error(f"Failed to create conversion campaign: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/switch-objective",
             summary="Switch campaign objective (creates new, pauses old)",
             description="Meta doesn't allow changing objectives on existing campaigns. "
                         "This creates a new campaign with the new objective, copies ad sets and ads, "
                         "then pauses the old campaign.")
def switch_objective(req: SwitchObjectiveRequest, db: Session = Depends(get_db)):
    """Switch a campaign's objective by creating a new one and pausing the old.

    Meta's API does not allow modifying campaign objectives after creation.
    This endpoint duplicates the campaign structure with the new objective.
    """
    access_token = _get_active_token(db)
    if not access_token or not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "Meta not configured"}

    # Get source campaign full structure
    source = _get_campaign_details(access_token, req.campaign_id)
    if not source:
        return {"status": "error", "message": f"Could not fetch campaign {req.campaign_id}"}

    source_name = source.get("name", "Unknown Campaign")
    source_objective = source.get("objective", "UNKNOWN")

    # Resolve pixel for conversion objectives
    pixel_id = None
    if req.new_objective in ("OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_ENGAGEMENT"):
        pixel_id = _resolve_pixel_id(access_token)
        if not pixel_id and req.new_objective == "OUTCOME_SALES":
            return {
                "status": "error",
                "message": "OUTCOME_SALES requires a pixel. Install Meta Pixel first via POST /api/v1/pixel/install.",
            }

    # Determine budget
    budget = req.daily_budget_cents
    if not budget:
        budget = int(source.get("daily_budget", 0)) or 1000

    try:
        # Step 1: Create new campaign
        camp_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/campaigns",
            data={
                "name": f"{source_name} ({req.new_objective})",
                "objective": req.new_objective,
                "status": "PAUSED",
                "special_ad_categories": json.dumps(source.get("special_ad_categories", [])),
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=20,
        )
        camp_result = camp_resp.json()
        if camp_resp.status_code >= 400 or not camp_result.get("id"):
            error_msg = camp_result.get("error", {}).get("message", str(camp_result))
            return {"status": "error", "step": "create_campaign", "message": error_msg}

        new_campaign_id = camp_result["id"]

        # Step 2: Copy each adset and its ads
        adsets_copied = []
        total_ads_copied = 0

        for src_adset in source.get("_adsets", []):
            adset_payload = {
                "campaign_id": new_campaign_id,
                "name": src_adset.get("name", "Adset"),
                "optimization_goal": req.optimization_goal,
                "billing_event": src_adset.get("billing_event", "IMPRESSIONS"),
                "daily_budget": str(budget),
                "status": "PAUSED",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            }

            # Copy targeting
            targeting = src_adset.get("targeting")
            if targeting:
                adset_payload["targeting"] = json.dumps(targeting)

            # Set promoted_object for conversion objectives
            if pixel_id and req.new_objective == "OUTCOME_SALES":
                adset_payload["promoted_object"] = json.dumps({
                    "pixel_id": pixel_id,
                    "custom_event_type": "PURCHASE",
                })

            adset_resp = requests.post(
                f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adsets",
                data=adset_payload,
                timeout=20,
            )
            adset_result = adset_resp.json()

            if adset_resp.status_code >= 400 or not adset_result.get("id"):
                error_msg = adset_result.get("error", {}).get("message", "")
                adsets_copied.append({"source_id": src_adset["id"], "error": error_msg})
                continue

            new_adset_id = adset_result["id"]
            ads_in_adset = 0

            # Copy ads
            for ad in src_adset.get("_ads", []):
                creative_id = ad.get("creative", {}).get("id")
                if not creative_id:
                    continue
                ad_resp = requests.post(
                    f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/ads",
                    data={
                        "name": ad.get("name", "Ad"),
                        "adset_id": new_adset_id,
                        "creative": json.dumps({"creative_id": creative_id}),
                        "status": "PAUSED",
                        "access_token": access_token,
                        "appsecret_proof": _appsecret_proof(access_token),
                    },
                    timeout=20,
                )
                if ad_resp.status_code == 200:
                    ads_in_adset += 1
                    total_ads_copied += 1

            adsets_copied.append({
                "source_id": src_adset["id"],
                "new_id": new_adset_id,
                "ads_copied": ads_in_adset,
            })

        # Step 3: Pause old campaign if requested
        old_paused = False
        if req.pause_old:
            pause_resp = requests.post(
                f"{META_GRAPH_BASE}/{req.campaign_id}",
                data={
                    "status": "PAUSED",
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            old_paused = pause_resp.status_code == 200 and pause_resp.json().get("success", False)

        _log_activity(
            db, "META_OBJECTIVE_SWITCHED", new_campaign_id,
            f"{source_objective} -> {req.new_objective} | "
            f"old={req.campaign_id} (paused={old_paused}) | "
            f"new={new_campaign_id} | adsets={len(adsets_copied)} | ads={total_ads_copied}",
        )

        return {
            "status": "created",
            "old_campaign": {
                "id": req.campaign_id,
                "name": source_name,
                "objective": source_objective,
                "paused": old_paused,
            },
            "new_campaign": {
                "id": new_campaign_id,
                "name": f"{source_name} ({req.new_objective})",
                "objective": req.new_objective,
                "optimization_goal": req.optimization_goal,
                "pixel_id": pixel_id,
                "daily_budget": f"${budget / 100:.2f}",
            },
            "adsets_copied": adsets_copied,
            "total_ads_copied": total_ads_copied,
            "next_steps": [
                "Review new campaign in Meta Ads Manager",
                f"Activate: POST /api/v1/meta/activate-campaign with campaign_id={new_campaign_id}",
                "Monitor for 3-5 days for Meta's learning phase",
            ],
        }

    except Exception as e:
        logger.error(f"Failed to switch objective: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/campaign-recommendations",
            summary="Campaign optimization recommendations",
            description="Analyze current campaigns and recommend objective changes, "
                        "budget adjustments, and audience modifications")
def campaign_recommendations(db: Session = Depends(get_db)):
    """Analyze all Meta campaigns and generate actionable recommendations.

    Checks pixel status, campaign objectives, performance metrics,
    and budget efficiency to recommend improvements.
    """
    access_token = _get_active_token(db)
    if not access_token or not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "Meta not configured"}

    recommendations = []
    campaign_analysis = []

    # Check pixel status
    pixel_id = _resolve_pixel_id(access_token)
    pixel_installed = bool(pixel_id)

    if not pixel_installed:
        recommendations.append({
            "priority": "CRITICAL",
            "category": "pixel",
            "title": "Install Meta Pixel",
            "detail": "No pixel found on ad account. Without a pixel, conversion "
                      "optimization (OUTCOME_SALES) is impossible. All campaigns are "
                      "flying blind — Meta cannot track purchases, add-to-carts, or any events.",
            "action": "POST /api/v1/pixel/install",
        })

    # Fetch all campaigns with insights
    try:
        from datetime import datetime, timedelta
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        resp = requests.get(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/campaigns",
            params={
                "fields": (
                    "id,name,status,daily_budget,objective,"
                    f"insights.time_range({{\"since\":\"{start_date}\",\"until\":\"{end_date}\"}})"
                    "{spend,impressions,clicks,ctr,cpc,actions,cost_per_action_type}"
                ),
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
                "limit": 50,
            },
            timeout=20,
        )
        resp.raise_for_status()
        campaigns = resp.json().get("data", [])
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch campaigns: {e}"}

    for camp in campaigns:
        camp_id = camp.get("id", "")
        name = camp.get("name", "")
        status = camp.get("status", "UNKNOWN")
        objective = camp.get("objective", "UNKNOWN")
        daily_budget = int(camp.get("daily_budget", 0))
        budget_dollars = daily_budget / 100 if daily_budget else 0

        insights = camp.get("insights", {}).get("data", [{}])
        insight = insights[0] if insights else {}
        spend = float(insight.get("spend", 0))
        clicks = int(insight.get("clicks", 0))
        impressions = int(insight.get("impressions", 0))
        ctr = float(insight.get("ctr", 0))
        cpc = float(insight.get("cpc", 0))

        # Extract conversions from actions
        purchases = 0
        for action in insight.get("actions", []):
            if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                purchases += int(action.get("value", 0))

        roas = 0
        analysis = {
            "campaign_id": camp_id,
            "name": name,
            "status": status,
            "objective": objective,
            "budget": f"${budget_dollars:.2f}/day",
            "spend_7d": round(spend, 2),
            "clicks_7d": clicks,
            "impressions_7d": impressions,
            "ctr_7d": round(ctr, 2),
            "cpc_7d": round(cpc, 2),
            "purchases_7d": purchases,
        }
        campaign_analysis.append(analysis)

        if status != "ACTIVE":
            continue

        # Recommendation: Wrong objective
        if objective in ("LINK_CLICKS", "POST_ENGAGEMENT", "BRAND_AWARENESS") and pixel_installed:
            recommendations.append({
                "priority": "HIGH",
                "category": "objective",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"Switch '{name}' from {objective} to OUTCOME_SALES",
                "detail": (
                    f"Campaign is using {objective} which optimizes for clicks, not purchases. "
                    f"With the pixel installed, switch to OUTCOME_SALES to optimize for revenue. "
                    f"Currently: ${spend:.2f} spend, {clicks} clicks, {purchases} purchases in 7 days."
                ),
                "action": f"POST /api/v1/meta/switch-objective with campaign_id={camp_id}",
            })
        elif objective in ("LINK_CLICKS", "POST_ENGAGEMENT") and not pixel_installed:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "objective",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"'{name}' needs OUTCOME_SALES but pixel must be installed first",
                "detail": (
                    f"Campaign uses {objective}. Install the pixel first, then switch objective. "
                    f"Current performance: ${spend:.2f} spend, {clicks} clicks, {ctr:.2f}% CTR."
                ),
                "action": "1) POST /api/v1/pixel/install  2) POST /api/v1/meta/switch-objective",
            })

        # Recommendation: High CPC
        if cpc > 0.50 and clicks > 10:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "budget",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"High CPC on '{name}': ${cpc:.2f}",
                "detail": (
                    f"CPC of ${cpc:.2f} is above $0.50 threshold. Consider: "
                    "refreshing ad creatives, narrowing audience targeting, "
                    "or testing different placements."
                ),
                "action": "Review ad creatives and audience overlap in Ads Manager",
            })

        # Recommendation: Low CTR
        if ctr < 1.0 and impressions > 1000:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "creative",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"Low CTR on '{name}': {ctr:.2f}%",
                "detail": (
                    f"CTR of {ctr:.2f}% is below 1% with {impressions} impressions. "
                    "Ad creative may not resonate with the audience. Test new images, "
                    "headlines, and primary text variations."
                ),
                "action": "POST /api/v1/meta/create-ad with new creative variations",
            })

        # Recommendation: Good performance, scale up
        if ctr > 3.0 and cpc < 0.20 and spend > 5:
            recommendations.append({
                "priority": "LOW",
                "category": "budget",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"Scale winner '{name}': {ctr:.2f}% CTR, ${cpc:.2f} CPC",
                "detail": (
                    f"Strong performance with {ctr:.2f}% CTR and ${cpc:.2f} CPC. "
                    f"Consider increasing budget from ${budget_dollars:.2f}/day. "
                    "Scale by 20-30% every 3 days to avoid disrupting the algorithm."
                ),
                "action": f"POST /api/v1/meta/set-budget with daily_budget_cents={int(daily_budget * 1.25)}",
            })

        # Recommendation: Zero purchases with significant spend
        if spend > 20 and purchases == 0 and pixel_installed:
            recommendations.append({
                "priority": "HIGH",
                "category": "conversion",
                "campaign_id": camp_id,
                "campaign_name": name,
                "title": f"${spend:.2f} spent with 0 purchases on '{name}'",
                "detail": (
                    "Significant ad spend with no conversions. Check: "
                    "1) Pixel is firing on checkout/purchase pages, "
                    "2) Landing page experience and load time, "
                    "3) Product pricing and shipping costs, "
                    "4) Checkout flow on mobile devices."
                ),
                "action": "GET /api/v1/pixel/verify and GET /api/v1/shopify/checkout-audit",
            })

    # Sort recommendations by priority
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    recommendations.sort(key=lambda r: priority_order.get(r.get("priority", "LOW"), 99))

    return {
        "status": "ok",
        "pixel_installed": pixel_installed,
        "pixel_id": pixel_id,
        "campaigns_analyzed": len(campaign_analysis),
        "recommendations_count": len(recommendations),
        "recommendations": recommendations,
        "campaigns": campaign_analysis,
    }


# ─── A/B Testing ─────────────────────────────────────────────────

class CreateABTestRequest(BaseModel):
    original_ad_id: str
    variant_type: str  # headline, image, cta
    variant_value: str  # New headline text, image URL/hash, or CTA type
    test_name: Optional[str] = None


def _get_ad_details(access_token: str, ad_id: str) -> Optional[dict]:
    """Fetch ad details including its creative, adset, and campaign."""
    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/{ad_id}",
            params={
                "fields": "id,name,status,adset_id,campaign_id,creative{id,name,title,body,image_url,image_hash,thumbnail_url,call_to_action_type,object_story_spec}",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch ad {ad_id}: {e}")
        return None


def _get_adset_budget(access_token: str, adset_id: str) -> Optional[dict]:
    """Fetch adset budget and campaign info."""
    try:
        resp = requests.get(
            f"{META_GRAPH_BASE}/{adset_id}",
            params={
                "fields": "id,name,daily_budget,campaign_id,targeting,optimization_goal,billing_event,promoted_object,status",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch adset {adset_id}: {e}")
        return None


@router.post("/create-test",
             summary="Create an A/B test for an ad creative",
             description="Duplicates an ad with a single variant change (headline, image, or CTA), "
                         "creates a parallel adset with 50/50 budget split, and tracks the test.")
def create_ab_test(req: CreateABTestRequest, db: Session = Depends(get_db)):
    """Create an A/B test by duplicating an ad and modifying one element.

    Workflow:
    1. Fetch original ad's creative details
    2. Create new creative with the variant change
    3. Create a new adset with half the original budget
    4. Reduce original adset budget to the other half
    5. Create the variant ad in the new adset
    6. Store test metadata in DB
    """
    from app.database import ABTestModel

    access_token = _get_active_token(db)
    if not access_token or not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "Meta not configured"}

    if req.variant_type not in ("headline", "image", "cta"):
        return {"status": "error", "message": "variant_type must be one of: headline, image, cta"}

    # Step 1: Get original ad details
    ad_details = _get_ad_details(access_token, req.original_ad_id)
    if not ad_details:
        return {"status": "error", "message": f"Could not fetch ad {req.original_ad_id}"}

    original_creative = ad_details.get("creative", {})
    original_adset_id = ad_details.get("adset_id")
    campaign_id = ad_details.get("campaign_id")
    ad_name = ad_details.get("name", "Ad")

    if not original_creative.get("id"):
        return {"status": "error", "message": "Original ad has no creative"}
    if not original_adset_id:
        return {"status": "error", "message": "Could not determine adset for this ad"}

    # Get original creative's object_story_spec
    original_oss = original_creative.get("object_story_spec", {})
    if not original_oss:
        # Fetch full creative
        try:
            cr_resp = requests.get(
                f"{META_GRAPH_BASE}/{original_creative['id']}",
                params={
                    "fields": "id,name,object_story_spec,image_hash,image_url",
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            cr_resp.raise_for_status()
            original_oss = cr_resp.json().get("object_story_spec", {})
        except Exception as e:
            return {"status": "error", "message": f"Could not fetch creative details: {e}"}

    if not original_oss:
        return {"status": "error", "message": "Creative has no object_story_spec — cannot clone"}

    # Step 2: Build variant creative by modifying the specified element
    variant_oss = json.loads(json.dumps(original_oss))  # Deep copy
    link_data = variant_oss.get("link_data", {})

    test_name = req.test_name or f"A/B Test: {req.variant_type} on {ad_name}"

    if req.variant_type == "headline":
        link_data["name"] = req.variant_value
    elif req.variant_type == "image":
        # variant_value can be an image URL or image hash
        if req.variant_value.startswith("http"):
            link_data["picture"] = req.variant_value
            link_data.pop("image_hash", None)
        else:
            link_data["image_hash"] = req.variant_value
            link_data.pop("picture", None)
    elif req.variant_type == "cta":
        cta_link = link_data.get("call_to_action", {}).get("value", {}).get("link", "")
        link_data["call_to_action"] = {
            "type": req.variant_value,
            "value": {"link": cta_link} if cta_link else {},
        }

    variant_oss["link_data"] = link_data

    try:
        # Create variant creative
        creative_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adcreatives",
            data={
                "name": f"[B] {test_name}",
                "object_story_spec": json.dumps(variant_oss),
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=20,
        )
        if creative_resp.status_code >= 400:
            error_body = creative_resp.json() if creative_resp.content else {}
            error_msg = error_body.get("error", {}).get("message", str(error_body))
            return {"status": "error", "step": "create_variant_creative", "message": error_msg}

        variant_creative_id = creative_resp.json().get("id")
        if not variant_creative_id:
            return {"status": "error", "step": "create_variant_creative", "message": "No creative ID returned"}

        # Step 3: Get original adset budget, split 50/50
        adset_info = _get_adset_budget(access_token, original_adset_id)
        if not adset_info:
            return {"status": "error", "step": "fetch_adset", "message": f"Could not fetch adset {original_adset_id}"}

        original_budget = int(adset_info.get("daily_budget", 0))
        half_budget = max(original_budget // 2, 100)  # Minimum $1.00/day

        # Create variant adset with half budget
        variant_adset_payload = {
            "campaign_id": campaign_id,
            "name": f"[B] {test_name}",
            "daily_budget": str(half_budget),
            "billing_event": adset_info.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": adset_info.get("optimization_goal", "LINK_CLICKS"),
            "status": "ACTIVE",
            "access_token": access_token,
            "appsecret_proof": _appsecret_proof(access_token),
        }

        targeting = adset_info.get("targeting")
        if targeting:
            variant_adset_payload["targeting"] = json.dumps(targeting)

        promoted_object = adset_info.get("promoted_object")
        if promoted_object:
            variant_adset_payload["promoted_object"] = json.dumps(promoted_object)

        adset_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adsets",
            data=variant_adset_payload,
            timeout=20,
        )
        if adset_resp.status_code >= 400:
            error_body = adset_resp.json() if adset_resp.content else {}
            error_msg = error_body.get("error", {}).get("message", str(error_body))
            return {"status": "error", "step": "create_variant_adset", "message": error_msg}

        variant_adset_id = adset_resp.json().get("id")
        if not variant_adset_id:
            return {"status": "error", "step": "create_variant_adset", "message": "No adset ID returned"}

        # Reduce original adset budget to half
        requests.post(
            f"{META_GRAPH_BASE}/{original_adset_id}",
            data={
                "daily_budget": str(half_budget),
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=15,
        )

        # Step 4: Create variant ad in the new adset
        ad_resp = requests.post(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/ads",
            data={
                "name": f"[B] {ad_name}",
                "adset_id": variant_adset_id,
                "creative": json.dumps({"creative_id": variant_creative_id}),
                "status": "ACTIVE",
                "access_token": access_token,
                "appsecret_proof": _appsecret_proof(access_token),
            },
            timeout=20,
        )
        if ad_resp.status_code >= 400:
            error_body = ad_resp.json() if ad_resp.content else {}
            error_msg = error_body.get("error", {}).get("message", str(error_body))
            return {"status": "error", "step": "create_variant_ad", "message": error_msg}

        variant_ad_id = ad_resp.json().get("id")

        # Step 5: Save test to DB
        ab_test = ABTestModel(
            test_name=test_name,
            campaign_id=campaign_id,
            original_ad_id=req.original_ad_id,
            variant_ad_id=variant_ad_id,
            original_adset_id=original_adset_id,
            variant_adset_id=variant_adset_id,
            variant_type=req.variant_type,
            variant_value=req.variant_value,
            status="running",
            original_budget_cents=original_budget,
        )
        db.add(ab_test)
        db.commit()
        db.refresh(ab_test)

        _log_activity(
            db, "AB_TEST_CREATED", str(ab_test.id),
            f"{test_name} | type={req.variant_type} | original={req.original_ad_id} | "
            f"variant={variant_ad_id} | budget_split=${half_budget / 100:.2f} each",
        )

        return {
            "status": "created",
            "test_id": ab_test.id,
            "test_name": test_name,
            "campaign_id": campaign_id,
            "original": {
                "ad_id": req.original_ad_id,
                "adset_id": original_adset_id,
                "budget": f"${half_budget / 100:.2f}/day",
            },
            "variant": {
                "ad_id": variant_ad_id,
                "adset_id": variant_adset_id,
                "creative_id": variant_creative_id,
                "budget": f"${half_budget / 100:.2f}/day",
                "variant_type": req.variant_type,
                "variant_value": req.variant_value,
            },
            "original_budget_was": f"${original_budget / 100:.2f}/day",
            "next_steps": [
                "Wait for both variants to accumulate >1000 impressions each",
                "Check results: GET /api/v1/meta/test-results",
                "Auto-optimize when ready: POST /api/v1/meta/auto-optimize",
            ],
        }

    except Exception as e:
        logger.error(f"Failed to create A/B test: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/test-results",
            summary="Get A/B test results with statistical significance",
            description="Fetches metrics for all running tests, calculates z-test for "
                        "CTR difference, returns winner/inconclusive with confidence level.")
def get_test_results(test_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Get performance comparison for A/B tests with statistical significance.

    Uses a two-proportion z-test on CTR to determine if the difference
    between original and variant is statistically significant.
    """
    import math
    from app.database import ABTestModel

    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    query = db.query(ABTestModel)
    if test_id:
        query = query.filter(ABTestModel.id == test_id)
    else:
        query = query.filter(ABTestModel.status == "running")

    tests = query.all()
    if not tests:
        return {"status": "ok", "message": "No running A/B tests found", "tests": []}

    results = []
    for test in tests:
        # Fetch insights for both ads (lifetime of the test)
        test_created = test.created_at.strftime("%Y-%m-%d") if test.created_at else "2026-01-01"
        from datetime import datetime as dt
        today = dt.utcnow().strftime("%Y-%m-%d")
        time_range = json.dumps({"since": test_created, "until": today})

        def _fetch_ad_insights(ad_id: str) -> dict:
            try:
                resp = requests.get(
                    f"{META_GRAPH_BASE}/{ad_id}/insights",
                    params={
                        "fields": "impressions,clicks,spend,ctr,cpc,actions,cost_per_action_type",
                        "time_range": time_range,
                        "access_token": access_token,
                        "appsecret_proof": _appsecret_proof(access_token),
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    return data[0] if data else {}
                return {}
            except Exception as e:
                logger.warning(f"Failed to fetch insights for ad {ad_id}: {e}")
                return {}

        original_insights = _fetch_ad_insights(test.original_ad_id)
        variant_insights = _fetch_ad_insights(test.variant_ad_id) if test.variant_ad_id else {}

        # Extract metrics
        orig_impressions = int(original_insights.get("impressions", 0))
        orig_clicks = int(original_insights.get("clicks", 0))
        orig_spend = float(original_insights.get("spend", 0))
        orig_ctr = orig_clicks / orig_impressions * 100 if orig_impressions > 0 else 0
        orig_cpc = orig_spend / orig_clicks if orig_clicks > 0 else 0

        var_impressions = int(variant_insights.get("impressions", 0))
        var_clicks = int(variant_insights.get("clicks", 0))
        var_spend = float(variant_insights.get("spend", 0))
        var_ctr = var_clicks / var_impressions * 100 if var_impressions > 0 else 0
        var_cpc = var_spend / var_clicks if var_clicks > 0 else 0

        # Two-proportion z-test for CTR
        total_impressions = orig_impressions + var_impressions
        confidence = 0.0
        z_score = 0.0
        significant = False
        winner = "inconclusive"

        if orig_impressions > 0 and var_impressions > 0:
            p1 = orig_clicks / orig_impressions
            p2 = var_clicks / var_impressions
            p_pool = (orig_clicks + var_clicks) / total_impressions
            se = math.sqrt(p_pool * (1 - p_pool) * (1 / orig_impressions + 1 / var_impressions)) if p_pool > 0 and p_pool < 1 else 0

            if se > 0:
                z_score = (p2 - p1) / se

                # Convert z-score to approximate confidence using normal CDF approximation
                abs_z = abs(z_score)
                # Abramowitz & Stegun approximation for standard normal CDF
                t = 1.0 / (1.0 + 0.2316419 * abs_z)
                d = 0.3989422804014327  # 1/sqrt(2*pi)
                prob = d * math.exp(-abs_z * abs_z / 2.0) * (
                    0.3193815 * t - 0.3565638 * t**2 + 1.781478 * t**3
                    - 1.821256 * t**4 + 1.330274 * t**5
                )
                # Two-tailed p-value
                p_value = 2 * prob
                confidence = round((1 - p_value) * 100, 2)

                significant = confidence >= 95.0
                if significant:
                    winner = "variant" if z_score > 0 else "original"

        # Update test record
        test.confidence_level = confidence
        if significant and (orig_impressions >= 1000 or var_impressions >= 1000):
            test.winner = winner
        db.commit()

        results.append({
            "test_id": test.id,
            "test_name": test.test_name,
            "variant_type": test.variant_type,
            "variant_value": test.variant_value,
            "status": test.status,
            "original": {
                "ad_id": test.original_ad_id,
                "impressions": orig_impressions,
                "clicks": orig_clicks,
                "ctr": round(orig_ctr, 3),
                "cpc": round(orig_cpc, 2),
                "spend": round(orig_spend, 2),
            },
            "variant": {
                "ad_id": test.variant_ad_id,
                "impressions": var_impressions,
                "clicks": var_clicks,
                "ctr": round(var_ctr, 3),
                "cpc": round(var_cpc, 2),
                "spend": round(var_spend, 2),
            },
            "statistics": {
                "z_score": round(z_score, 4),
                "confidence_pct": confidence,
                "significant": significant,
                "winner": winner,
                "min_impressions_met": orig_impressions >= 1000 and var_impressions >= 1000,
                "total_impressions": total_impressions,
            },
            "ctr_lift": round(var_ctr - orig_ctr, 3) if orig_impressions > 0 and var_impressions > 0 else None,
            "ctr_lift_pct": round((var_ctr - orig_ctr) / orig_ctr * 100, 1) if orig_ctr > 0 else None,
        })

    return {
        "status": "ok",
        "tests_analyzed": len(results),
        "results": results,
    }


@router.post("/auto-optimize",
             summary="Auto-optimize completed A/B tests",
             description="Checks running tests with >1000 impressions and >95% confidence. "
                         "Pauses the losing variant and reallocates budget to the winner.")
def auto_optimize_tests(db: Session = Depends(get_db)):
    """Automatically pick winners and reallocate budget for mature A/B tests.

    For each running test where both variants have 1000+ impressions
    and statistical confidence is 95%+:
    1. Pause the losing ad's adset
    2. Restore full budget to the winning ad's adset
    3. Mark test as completed
    """
    from datetime import datetime as dt
    from app.database import ABTestModel

    access_token = _get_active_token(db)
    if not access_token:
        return {"status": "error", "message": "No Meta token available"}

    # First refresh results for all running tests
    results_resp = get_test_results(db=db)
    if results_resp.get("status") != "ok":
        return results_resp

    test_results = results_resp.get("results", [])
    optimized = []
    skipped = []

    for result in test_results:
        test_id = result["test_id"]
        stats = result.get("statistics", {})
        confidence = stats.get("confidence_pct", 0)
        winner = stats.get("winner", "inconclusive")
        min_met = stats.get("min_impressions_met", False)

        if not min_met:
            skipped.append({
                "test_id": test_id,
                "test_name": result["test_name"],
                "reason": f"Need 1000+ impressions each (original={result['original']['impressions']}, variant={result['variant']['impressions']})",
            })
            continue

        if confidence < 95.0 or winner == "inconclusive":
            skipped.append({
                "test_id": test_id,
                "test_name": result["test_name"],
                "reason": f"Confidence {confidence}% < 95% threshold",
            })
            continue

        # This test has a winner — optimize
        test = db.query(ABTestModel).filter(ABTestModel.id == test_id).first()
        if not test or test.status != "running":
            continue

        if winner == "variant":
            loser_adset_id = test.original_adset_id
            winner_adset_id = test.variant_adset_id
            winner_ad_id = test.variant_ad_id
        else:
            loser_adset_id = test.variant_adset_id
            winner_adset_id = test.original_adset_id
            winner_ad_id = test.original_ad_id

        # Pause losing adset
        pause_ok = False
        try:
            pause_resp = requests.post(
                f"{META_GRAPH_BASE}/{loser_adset_id}",
                data={
                    "status": "PAUSED",
                    "access_token": access_token,
                    "appsecret_proof": _appsecret_proof(access_token),
                },
                timeout=15,
            )
            pause_ok = pause_resp.status_code == 200 and pause_resp.json().get("success", False)
        except Exception as e:
            logger.warning(f"Failed to pause losing adset {loser_adset_id}: {e}")

        # Restore full budget to winner
        budget_ok = False
        full_budget = test.original_budget_cents or 0
        if full_budget > 0 and winner_adset_id:
            try:
                budget_resp = requests.post(
                    f"{META_GRAPH_BASE}/{winner_adset_id}",
                    data={
                        "daily_budget": str(full_budget),
                        "access_token": access_token,
                        "appsecret_proof": _appsecret_proof(access_token),
                    },
                    timeout=15,
                )
                budget_ok = budget_resp.status_code == 200 and budget_resp.json().get("success", False)
            except Exception as e:
                logger.warning(f"Failed to restore budget on winner adset {winner_adset_id}: {e}")

        # Update test record
        test.status = f"winner_{winner}"
        test.winner = winner
        test.confidence_level = confidence
        test.completed_at = dt.utcnow()
        db.commit()

        _log_activity(
            db, "AB_TEST_OPTIMIZED", str(test_id),
            f"Winner: {winner} (ad {winner_ad_id}) | confidence={confidence}% | "
            f"loser_paused={pause_ok} | budget_restored={budget_ok} (${full_budget / 100:.2f}/day)",
        )

        optimized.append({
            "test_id": test_id,
            "test_name": test.test_name,
            "winner": winner,
            "winner_ad_id": winner_ad_id,
            "confidence": confidence,
            "loser_adset_paused": pause_ok,
            "budget_restored": budget_ok,
            "restored_budget": f"${full_budget / 100:.2f}/day" if full_budget else "unknown",
        })

    return {
        "status": "ok",
        "optimized_count": len(optimized),
        "skipped_count": len(skipped),
        "optimized": optimized,
        "skipped": skipped,
    }
