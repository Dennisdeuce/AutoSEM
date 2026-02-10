"""TikTok Ads router - OAuth, campaign creation, and performance tracking"""

import os
import json
import logging
import time
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, TikTokTokenModel, CampaignModel, ActivityLogModel

logger = logging.getLogger("AutoSEM.TikTok")
router = APIRouter()

TIKTOK_APP_ID = os.environ.get("TIKTOK_APP_ID", "7602833892719542273")
TIKTOK_APP_SECRET = os.environ.get("TIKTOK_APP_SECRET", "b2d479247984871ef1b6f26c1639bf36ad822c21")
TIKTOK_REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "https://auto-sem.replit.app/api/v1/tiktok/callback")
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

PRODUCT_IMAGES = [
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-tennis-hoodie-921535.jpg?v=1708170515",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-tennis-hoodie-404401.jpg?v=1708087650",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-performance-crew-neck-tennis-t-shirt-999403.jpg?v=1707157727",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-performance-crew-neck-tennis-t-shirt-987369.jpg?v=1707157699",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/womens-relaxed-victory-court-t-shirt-806307.jpg?v=1706822921",
]


def _get_active_token(db: Session) -> dict:
    try:
        token_record = db.query(TikTokTokenModel).first()
        if token_record and token_record.access_token:
            return {"access_token": token_record.access_token, "advertiser_id": token_record.advertiser_id}
    except Exception:
        pass
    return {"access_token": os.environ.get("TIKTOK_ACCESS_TOKEN", ""), "advertiser_id": os.environ.get("TIKTOK_ADVERTISER_ID", "")}


def _tiktok_api(method: str, endpoint: str, access_token: str, params: dict = None, data: dict = None) -> dict:
    url = f"{TIKTOK_API_BASE}{endpoint}"
    headers = {"Access-Token": access_token, "Content-Type": "application/json"}
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        else:
            resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"TikTok API error: {e}")
        return {"code": -1, "message": str(e)}


def _find_best_identity(access_token: str, advertiser_id: str) -> dict:
    for identity_type in ["TT_USER", "BC_AUTH_TT"]:
        result = _tiktok_api("GET", "/identity/get/", access_token,
                             params={"advertiser_id": advertiser_id, "identity_type": identity_type})
        if result.get("code") == 0:
            identities = result.get("data", {}).get("identity_list", [])
            if identities:
                return {"identity_id": identities[0].get("identity_id"),
                        "identity_type": identity_type,
                        "display_name": identities[0].get("display_name", "")}
    return {}


def _upload_images(access_token: str, advertiser_id: str, image_urls: list) -> list:
    """Upload multiple images, return list of image_ids."""
    image_ids = []
    for url in image_urls:
        result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
            "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": url,
        })
        if result.get("code") == 0:
            img_id = result.get("data", {}).get("image_id", "")
            if img_id:
                image_ids.append(img_id)
        elif result.get("code") == 40911:
            # Duplicate - use material_id to find it, or just note it
            logger.info(f"Duplicate image: {url}")
    return image_ids


def _upload_image(access_token: str, advertiser_id: str, image_url: str) -> str:
    """Upload single image, handle duplicates by trying all available images."""
    result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
        "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": image_url,
    })
    if result.get("code") == 0:
        return result.get("data", {}).get("image_id", "")
    if result.get("code") == 40911:
        logger.info(f"Duplicate image, trying alternatives...")
        # Try other product images
        for alt_url in PRODUCT_IMAGES:
            if alt_url != image_url:
                alt_result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
                    "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": alt_url,
                })
                if alt_result.get("code") == 0:
                    return alt_result.get("data", {}).get("image_id", "")
                if alt_result.get("code") == 40911:
                    continue
        # All duplicates - get from Shopify with unique timestamp
        unique_url = image_url + ("&" if "?" in image_url else "?") + f"t={int(time.time())}"
        final = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
            "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL",
            "image_url": image_url, "file_name": f"court_sportswear_{int(time.time())}.jpg",
        })
        if final.get("code") == 0:
            return final.get("data", {}).get("image_id", "")
    logger.warning(f"Image upload failed: {result.get('message')}")
    return ""


def _create_slideshow_video(access_token: str, advertiser_id: str, image_ids: list) -> str:
    """Create a slideshow video from multiple images using TikTok creative tools."""
    if len(image_ids) < 1:
        return ""
    # Method 1: Smart Creative slideshow
    result = _tiktok_api("POST", "/creative/assets/slideshow/create/", access_token, data={
        "advertiser_id": advertiser_id,
        "image_ids": image_ids[:5],
    })
    if result.get("code") == 0:
        video_id = result.get("data", {}).get("video_id", "")
        if video_id:
            return video_id
    # Method 2: Image-to-video
    result = _tiktok_api("POST", "/file/video/ad/upload/", access_token, data={
        "advertiser_id": advertiser_id,
        "upload_type": "UPLOAD_BY_VIDEO_ID",
        "image_ids": image_ids[:1],
    })
    if result.get("code") == 0:
        return result.get("data", {}).get("video_id", "")
    logger.info(f"Slideshow creation result: {result}")
    return ""


def _get_product_images() -> list:
    try:
        resp = requests.get("https://court-sportswear.com/products.json?limit=10", timeout=10)
        if resp.status_code == 200:
            urls = []
            for p in resp.json().get("products", []):
                for img in p.get("images", [])[:1]:
                    src = img.get("src", "")
                    if src:
                        urls.append(src)
            if urls:
                return urls
    except Exception:
        pass
    return PRODUCT_IMAGES


def _try_create_ad(access_token: str, advertiser_id: str, adgroup_id: str,
                   image_id: str, identity: dict, video_id: str = "",
                   campaign_id: str = "") -> dict:
    """Try multiple ad creation strategies. TikTok feed needs video; Pangle accepts images."""
    identity_id = identity.get("identity_id", "")
    identity_type = identity.get("identity_type", "")
    attempts = []

    base = {
        "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
        "landing_page_url": "https://court-sportswear.com/collections/all",
        "call_to_action": "SHOP_NOW",
        "identity_id": identity_id,
        "identity_type": identity_type,
    }

    # Strategy 1: Video ad (TikTok native - works everywhere)
    if video_id:
        creative = {**base, "ad_name": "Court Sportswear - Tennis Video",
                    "ad_format": "SINGLE_VIDEO", "video_id": video_id}
        if image_id:
            creative["image_ids"] = [image_id]
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "video_ad", "code": result.get("code"), "message": result.get("message")})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    # Strategy 2: Image carousel (multiple images displayed as swipeable)
    if image_id:
        creative = {**base, "ad_name": "Court Sportswear - Tennis Collection",
                    "ad_format": "SINGLE_IMAGE", "image_ids": [image_id]}
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "single_image", "code": result.get("code"), "message": result.get("message")})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    # Strategy 3: Create a NEW ad group with Pangle placement (accepts images)
    if image_id and campaign_id:
        schedule_start = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_id": campaign_id,
            "adgroup_name": "Court Sportswear - Pangle Image Ads",
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_PANGLE"],
            "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY", "budget": 20.0,
            "schedule_type": "SCHEDULE_FROM_NOW", "schedule_start_time": schedule_start,
            "billing_event": "CPC", "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID", "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE",
            "location_ids": ["6252001"], "gender": "GENDER_UNLIMITED",
            "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        })
        attempts.append({"strategy": "create_pangle_adgroup", "code": ag_result.get("code"),
                         "message": ag_result.get("message")})
        if ag_result.get("code") == 0:
            pangle_ag_id = ag_result.get("data", {}).get("adgroup_id")
            creative = {**base, "ad_name": "Court Sportswear - Pangle Image",
                        "ad_format": "SINGLE_IMAGE", "image_ids": [image_id]}
            ad_result = _tiktok_api("POST", "/ad/create/", access_token, data={
                "advertiser_id": advertiser_id, "adgroup_id": pangle_ag_id,
                "creatives": [creative], "operation_status": "ENABLE"})
            attempts.append({"strategy": "pangle_image_ad", "code": ad_result.get("code"),
                             "message": ad_result.get("message"), "adgroup_id": pangle_ag_id})
            if ad_result.get("code") == 0:
                return {"success": True, "ad_ids": ad_result.get("data", {}).get("ad_ids", []),
                        "pangle_adgroup_id": pangle_ag_id, "attempts": attempts}

    return {"success": False, "attempts": attempts}


# ── OAuth & Token Endpoints ──

@router.get("/connect", summary="Connect TikTok")
def connect_tiktok():
    if not TIKTOK_APP_ID:
        return {"error": "TIKTOK_APP_ID not configured"}
    return RedirectResponse(url=f"https://business-api.tiktok.com/portal/auth?app_id={TIKTOK_APP_ID}&state=autosem_connect&redirect_uri={TIKTOK_REDIRECT_URI}")


@router.get("/callback", summary="OAuth Callback")
def oauth_callback(auth_code: str = Query(None), code: str = Query(None),
                   state: str = Query(None), error: str = Query(None),
                   db: Session = Depends(get_db)):
    the_code = auth_code or code
    if error:
        return HTMLResponse(content=f"<h1>Error</h1><p>{error}</p>")
    if not the_code:
        return HTMLResponse(content="<h1>Error</h1><p>No auth code received.</p>")
    result = _exchange_token(the_code, db)
    if result.get("success"):
        adv_id = result.get("advertiser_id", "unknown")
        token = result.get("_token", "")
        return HTMLResponse(content=f'''<!DOCTYPE html><html><head><title>TikTok Connected</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:40px auto;padding:20px;background:#f5f5f5}}
.card{{background:white;border-radius:12px;padding:30px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:20px}}
h1{{color:#28a745}}</style></head><body>
<div class="card"><h1>TikTok Connected!</h1><p>Advertiser ID: <strong>{adv_id}</strong></p>
<p><a href="/dashboard">Go to Dashboard</a></p></div></body></html>''')
    return HTMLResponse(content=f"<h1>Error</h1><p>{result.get('error')}</p>")


@router.post("/exchange-token", summary="Exchange auth code for access token")
def exchange_token_endpoint(auth_code: str = Query(...), db: Session = Depends(get_db)):
    return _exchange_token(auth_code, db)


def _exchange_token(auth_code: str, db: Session) -> dict:
    try:
        resp = requests.post(f"{TIKTOK_API_BASE}/oauth2/access_token/",
                             json={"app_id": TIKTOK_APP_ID, "secret": TIKTOK_APP_SECRET, "auth_code": auth_code}, timeout=30)
        result = resp.json()
        if result.get("code") != 0:
            return {"success": False, "error": result.get("message")}
        data = result.get("data", {})
        access_token = data.get("access_token")
        advertiser_ids = data.get("advertiser_ids", [])
        advertiser_id = advertiser_ids[0] if advertiser_ids else ""
        if not access_token:
            return {"success": False, "error": "No access token"}
        existing = db.query(TikTokTokenModel).first()
        if existing:
            existing.access_token = access_token
            existing.advertiser_id = advertiser_id
            existing.advertiser_ids = json.dumps(advertiser_ids)
            existing.updated_at = datetime.utcnow()
        else:
            db.add(TikTokTokenModel(access_token=access_token, advertiser_id=advertiser_id,
                                    advertiser_ids=json.dumps(advertiser_ids)))
        db.commit()
        return {"success": True, "advertiser_id": advertiser_id, "_token": access_token}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/status", summary="Check TikTok Status")
def check_tiktok_status(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"connected": False, "message": "No TikTok token found"}
    result = _tiktok_api("GET", "/oauth2/advertiser/get/", creds["access_token"],
                        params={"app_id": TIKTOK_APP_ID, "secret": TIKTOK_APP_SECRET})
    if result.get("code") == 0:
        return {"connected": True, "advertiser_id": creds["advertiser_id"],
                "advertisers": result.get("data", {}).get("list", [])}
    return {"connected": False, "message": result.get("message")}


# ── Campaign & Ad Creation ──

@router.post("/launch-campaign", summary="Launch TikTok Ad Campaign")
def launch_campaign(daily_budget: float = Query(20.0),
                    campaign_name: str = Query("Court Sportswear - Tennis Apparel"),
                    db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected."}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []
    adgroup_budget = max(daily_budget, 20.0)

    try:
        # Create campaign
        camp = _tiktok_api("POST", "/campaign/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_name": campaign_name,
            "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE"})
        steps.append({"step": "campaign", "code": camp.get("code"), "message": camp.get("message")})
        if camp.get("code") != 0:
            return {"success": False, "error": camp.get("message"), "steps": steps}
        campaign_id = camp["data"]["campaign_id"]

        # Create ad group (automatic placement for videos)
        schedule = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        ag = _tiktok_api("POST", "/adgroup/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_id": campaign_id,
            "adgroup_name": f"{campaign_name} - US Tennis 25-55",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC", "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY", "budget": adgroup_budget,
            "schedule_type": "SCHEDULE_FROM_NOW", "schedule_start_time": schedule,
            "billing_event": "CPC", "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID", "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE", "location_ids": ["6252001"],
            "gender": "GENDER_UNLIMITED", "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"]})
        steps.append({"step": "adgroup", "code": ag.get("code"), "message": ag.get("message")})
        if ag.get("code") != 0:
            return {"success": False, "error": ag.get("message"), "steps": steps}
        adgroup_id = ag["data"]["adgroup_id"]

        # Upload images
        product_urls = _get_product_images()[:5]
        image_ids = _upload_images(access_token, advertiser_id, product_urls)
        steps.append({"step": "upload_images", "count": len(image_ids), "image_ids": image_ids})

        # Try slideshow video from multiple images
        video_id = ""
        if len(image_ids) >= 2:
            video_id = _create_slideshow_video(access_token, advertiser_id, image_ids)
            steps.append({"step": "slideshow", "video_id": video_id})

        # Find identity
        identity = _find_best_identity(access_token, advertiser_id)
        steps.append({"step": "identity", "result": identity})

        image_id = image_ids[0] if image_ids else ""

        # Try ad creation (video first, then image with Pangle fallback)
        ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                    image_id, identity, video_id, campaign_id)
        steps.append({"step": "create_ad", "result": ad_result})

        ad_id = None
        if ad_result.get("success"):
            ad_ids = ad_result.get("ad_ids", [])
            ad_id = ad_ids[0] if ad_ids else None

        db.add(CampaignModel(platform="tiktok", platform_campaign_id=str(campaign_id),
                             name=campaign_name, status="ACTIVE", campaign_type="TRAFFIC",
                             daily_budget=adgroup_budget))
        db.add(ActivityLogModel(action="TIKTOK_CAMPAIGN_LAUNCHED", entity_type="campaign",
                                entity_id=str(campaign_id),
                                details=f"Campaign: {campaign_id}, AdGroup: {adgroup_id}, Ad: {ad_id}"))
        db.commit()

        return {"success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id,
                "ad_id": ad_id, "daily_budget": adgroup_budget,
                "ad_warning": None if ad_id else "Ad creation pending - try video upload",
                "steps": steps}
    except Exception as e:
        return {"success": False, "error": str(e), "steps": steps}


@router.post("/create-ad-for-adgroup", summary="Create ad for existing ad group")
def create_ad_for_adgroup(adgroup_id: str = Query(...),
                          campaign_id: str = Query("1856672017238274"),
                          image_url: str = Query(None),
                          db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []

    # Upload images
    if image_url:
        image_id = _upload_image(access_token, advertiser_id, image_url)
        image_ids = [image_id] if image_id else []
    else:
        urls = _get_product_images()[:5]
        image_ids = _upload_images(access_token, advertiser_id, urls)
    steps.append({"step": "images", "count": len(image_ids), "ids": image_ids})

    if not image_ids:
        return {"success": False, "error": "No images could be uploaded", "steps": steps}

    # Try slideshow
    video_id = ""
    if len(image_ids) >= 2:
        video_id = _create_slideshow_video(access_token, advertiser_id, image_ids)
    steps.append({"step": "slideshow", "video_id": video_id})

    # Identity
    identity = _find_best_identity(access_token, advertiser_id)
    steps.append({"step": "identity", "result": identity})
    if not identity.get("identity_id"):
        return {"success": False, "error": "No identity found", "steps": steps}

    # Try ad creation with all strategies including Pangle fallback
    ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                image_ids[0], identity, video_id, campaign_id)
    steps.append({"step": "create_ad", "result": ad_result})

    if ad_result.get("success"):
        return {"success": True, "ad_ids": ad_result.get("ad_ids", []),
                "pangle_adgroup": ad_result.get("pangle_adgroup_id"),
                "video_id": video_id, "steps": steps}
    return {"success": False, "error": "All strategies failed", "steps": steps}


# ── Debug & Info Endpoints ──

@router.get("/images", summary="List uploaded images")
def list_images(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/file/image/ad/get/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"], "page_size": 50})
    images = result.get("data", {}).get("list", []) if result.get("code") == 0 else []
    return {"count": len(images), "images": images, "raw_code": result.get("code"),
            "raw_message": result.get("message")}


@router.get("/identities", summary="List all TikTok identities")
def list_identities(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    all_ids = {}
    for it in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"], "identity_type": it})
        lst = result.get("data", {}).get("identity_list", []) if result.get("code") == 0 else []
        all_ids[it] = {"count": len(lst), "list": lst}
    return {"advertiser_id": creds["advertiser_id"], "identities": all_ids}


@router.get("/debug-image-upload", summary="Test image upload")
def debug_image_upload(image_url: str = Query(PRODUCT_IMAGES[0]), db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("POST", "/file/image/ad/upload/", creds["access_token"], data={
        "advertiser_id": creds["advertiser_id"], "upload_type": "UPLOAD_BY_URL", "image_url": image_url})
    return {"image_url": image_url, "result": result}


@router.post("/debug-slideshow", summary="Test slideshow video creation")
def debug_slideshow(db: Session = Depends(get_db)):
    """Upload multiple images and try creating a slideshow video."""
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    urls = _get_product_images()[:5]
    image_ids = _upload_images(access_token, advertiser_id, urls)
    video_id = _create_slideshow_video(access_token, advertiser_id, image_ids) if image_ids else ""
    return {"image_ids": image_ids, "video_id": video_id, "urls_tried": len(urls)}


@router.get("/performance", summary="Get TikTok Performance Data")
def get_tiktok_performance(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"error": "TikTok not connected"}
    try:
        result = _tiktok_api("GET", "/campaign/get/", creds["access_token"],
                           params={"advertiser_id": creds["advertiser_id"], "page_size": 100})
        campaigns = []
        if result.get("code") == 0:
            for c in result.get("data", {}).get("list", []):
                campaigns.append({"id": c.get("campaign_id"), "name": c.get("campaign_name"),
                                  "status": c.get("operation_status"), "budget": c.get("budget", 0),
                                  "objective": c.get("objective_type")})
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        total_spend = total_imp = total_clicks = 0
        stats = _tiktok_api("GET", "/report/integrated/get/", creds["access_token"], params={
            "advertiser_id": creds["advertiser_id"], "report_type": "BASIC",
            "dimensions": json.dumps(["campaign_id"]), "data_level": "AUCTION_CAMPAIGN",
            "start_date": start, "end_date": end,
            "metrics": json.dumps(["spend", "impressions", "clicks", "ctr", "cpc", "reach"])})
        if stats.get("code") == 0:
            for row in stats.get("data", {}).get("list", []):
                m = row.get("metrics", {})
                total_spend += float(m.get("spend", 0))
                total_imp += int(m.get("impressions", 0))
                total_clicks += int(m.get("clicks", 0))
        return {"summary": {"total_campaigns": len(campaigns), "total_spend": round(total_spend, 2),
                            "total_impressions": total_imp, "total_clicks": total_clicks,
                            "avg_ctr": round((total_clicks / total_imp * 100) if total_imp else 0, 2),
                            "avg_cpc": round((total_spend / total_clicks) if total_clicks else 0, 2)},
                "campaigns": campaigns}
    except Exception as e:
        return {"error": str(e)}


@router.get("/advertiser-info", summary="Get advertiser info")
def get_advertiser_info(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    return _tiktok_api("GET", "/advertiser/info/", creds["access_token"],
                       params={"advertiser_ids": json.dumps([creds["advertiser_id"]])})
