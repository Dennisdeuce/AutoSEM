"""TikTok Ads router - OAuth, campaign creation, and performance tracking"""

import os
import json
import logging
import time
import hashlib
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
    for identity_type in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", access_token,
                             params={"advertiser_id": advertiser_id, "identity_type": identity_type})
        if result.get("code") == 0:
            identities = result.get("data", {}).get("identity_list", [])
            if identities:
                identity = identities[0]
                return {"identity_id": identity.get("identity_id"), "identity_type": identity_type,
                        "display_name": identity.get("display_name", "")}
    return {}


def _get_existing_images(access_token: str, advertiser_id: str) -> list:
    result = _tiktok_api("GET", "/file/image/ad/get/", access_token,
                         params={"advertiser_id": advertiser_id, "page_size": 20})
    if result.get("code") == 0:
        return result.get("data", {}).get("list", [])
    return []


def _upload_image(access_token: str, advertiser_id: str, image_url: str) -> str:
    upload_data = {
        "advertiser_id": advertiser_id,
        "upload_type": "UPLOAD_BY_URL",
        "image_url": image_url,
    }
    result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data=upload_data)
    if result.get("code") == 0:
        image_id = result.get("data", {}).get("image_id", "")
        if image_id:
            return image_id
    if result.get("code") == 40911:
        existing = _get_existing_images(access_token, advertiser_id)
        if existing:
            return existing[0].get("image_id", "")
    logger.warning(f"Image upload failed: {result.get('message')}")
    return ""


def _generate_video_from_image(access_token: str, advertiser_id: str, image_id: str) -> str:
    """Use TikTok Smart Creative to generate a video from an image."""
    # Try the video generation endpoint
    gen_data = {
        "advertiser_id": advertiser_id,
        "image_id": image_id,
        "ratio": "9:16",
    }
    result = _tiktok_api("POST", "/creative/smart_video/create/", access_token, data=gen_data)
    if result.get("code") == 0:
        task_id = result.get("data", {}).get("task_id", "")
        if task_id:
            # Poll for completion
            for _ in range(10):
                time.sleep(3)
                check = _tiktok_api("GET", "/creative/smart_video/get/", access_token,
                                    params={"advertiser_id": advertiser_id, "task_id": task_id})
                if check.get("code") == 0:
                    status = check.get("data", {}).get("status", "")
                    if status == "SUCCESS":
                        return check.get("data", {}).get("video_id", "")
                    elif status == "FAILED":
                        break
    logger.warning(f"Video generation failed: {result.get('message')}")
    return ""


def _get_product_images() -> list:
    try:
        resp = requests.get("https://court-sportswear.com/products.json?limit=5", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            urls = []
            for p in data.get("products", []):
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
                   image_id: str, identity: dict, video_id: str = "") -> dict:
    """Try multiple ad creation strategies."""
    identity_id = identity.get("identity_id", "")
    identity_type = identity.get("identity_type", "")
    display_name = identity.get("display_name", "Court Sportswear")
    attempts = []

    base_fields = {
        "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
        "landing_page_url": "https://court-sportswear.com/collections/all",
        "call_to_action": "SHOP_NOW",
        "identity_id": identity_id,
        "identity_type": identity_type,
    }

    # Strategy 1: Video ad (TikTok's native format)
    if video_id:
        creative = {**base_fields,
            "ad_name": "Court Sportswear - Tennis Apparel Video",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
        }
        if image_id:
            creative["image_ids"] = [image_id]  # thumbnail
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE",
        })
        attempts.append({"strategy": "video_ad", "result": result})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    # Strategy 2: Image ad with SINGLE_IMAGE format
    if image_id:
        creative = {**base_fields,
            "ad_name": "Court Sportswear - Tennis Apparel",
            "ad_format": "SINGLE_IMAGE",
            "image_ids": [image_id],
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE",
        })
        attempts.append({"strategy": "single_image", "result": result})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    # Strategy 3: Image ad without CTA (sometimes CTA causes issues)
    if image_id:
        creative = {
            "ad_name": "Court Sportswear - Performance Tennis Gear",
            "ad_text": "Premium tennis & pickleball apparel. Shop court-sportswear.com",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "ad_format": "SINGLE_IMAGE",
            "identity_id": identity_id,
            "identity_type": identity_type,
            "image_ids": [image_id],
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE",
        })
        attempts.append({"strategy": "image_no_cta", "result": result})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    # Strategy 4: CUSTOMIZED_USER identity (fallback for compatibility)
    if image_id and identity_type != "CUSTOMIZED_USER":
        cust_identity = None
        cust_result = _tiktok_api("GET", "/identity/get/", access_token,
                                  params={"advertiser_id": advertiser_id, "identity_type": "CUSTOMIZED_USER"})
        if cust_result.get("code") == 0:
            cust_list = cust_result.get("data", {}).get("identity_list", [])
            if cust_list:
                cust_identity = cust_list[0]

        if cust_identity:
            creative = {
                "ad_name": "Court Sportswear - Tennis Collection",
                "ad_text": "Premium tennis & pickleball apparel. Shop now!",
                "landing_page_url": "https://court-sportswear.com/collections/all",
                "call_to_action": "SHOP_NOW",
                "ad_format": "SINGLE_IMAGE",
                "identity_id": cust_identity.get("identity_id"),
                "identity_type": "CUSTOMIZED_USER",
                "image_ids": [image_id],
            }
            result = _tiktok_api("POST", "/ad/create/", access_token, data={
                "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
                "creatives": [creative], "operation_status": "ENABLE",
            })
            attempts.append({"strategy": "customized_user_fallback", "result": result})
            if result.get("code") == 0:
                return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []), "attempts": attempts}

    return {"success": False, "attempts": attempts}


@router.get("/connect", summary="Connect TikTok")
def connect_tiktok():
    if not TIKTOK_APP_ID:
        return {"error": "TIKTOK_APP_ID not configured"}
    return RedirectResponse(url=f"https://business-api.tiktok.com/portal/auth?app_id={TIKTOK_APP_ID}&state=autosem_connect&redirect_uri={TIKTOK_REDIRECT_URI}")


@router.get("/callback", summary="OAuth Callback")
def oauth_callback(auth_code: str = Query(None), code: str = Query(None), state: str = Query(None), error: str = Query(None), db: Session = Depends(get_db)):
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
<style>body{{font-family:Segoe UI,sans-serif;max-width:700px;margin:40px auto;padding:20px;background:#f5f5f5}}
.card{{background:white;border-radius:12px;padding:30px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:20px}}
h1{{color:#28a745}}.sb{{background:#1e1e1e;color:#4ec9b0;padding:14px 18px;border-radius:8px;font-family:monospace;font-size:.85em;word-break:break-all;margin:8px 0;position:relative}}
.cb{{position:absolute;top:8px;right:8px;background:#4338ca;color:white;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.8em}}
.step{{padding:12px 16px;background:#f0fdf4;border-left:4px solid #28a745;border-radius:4px;margin:10px 0}}</style></head><body>
<div class="card"><h1>TikTok Connected!</h1><p>Advertiser ID: <strong>{adv_id}</strong></p></div>
<div class="card"><h2>Replit Secrets</h2><div class="step"><strong>Step 1:</strong> Add these as Replit Secrets</div>
<p><strong>TIKTOK_ACCESS_TOKEN</strong></p><div class="sb" id="tb">{token}<button class="cb" onclick="copyT('tb')">Copy</button></div>
<p><strong>TIKTOK_ADVERTISER_ID</strong></p><div class="sb" id="ab">{adv_id}<button class="cb" onclick="copyT('ab')">Copy</button></div></div>
<div class="card"><a href="/dashboard">Go to Dashboard</a></div>
<script>function copyT(id){{var e=document.getElementById(id);navigator.clipboard.writeText(e.textContent.replace("Copy","").trim());e.querySelector(".cb").textContent="Copied!";setTimeout(function(){{e.querySelector(".cb").textContent="Copy"}},2000)}}</script></body></html>''')
    return HTMLResponse(content=f"<h1>Error</h1><p>{result.get('error', 'Unknown error')}</p>")


@router.post("/exchange-token", summary="Exchange auth code for access token")
def exchange_token_endpoint(auth_code: str = Query(...), db: Session = Depends(get_db)):
    return _exchange_token(auth_code, db)


def _exchange_token(auth_code: str, db: Session) -> dict:
    try:
        resp = requests.post(f"{TIKTOK_API_BASE}/oauth2/access_token/",
                             json={"app_id": TIKTOK_APP_ID, "secret": TIKTOK_APP_SECRET, "auth_code": auth_code}, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            return {"success": False, "error": result.get("message", "Token exchange failed")}
        data = result.get("data", {})
        access_token = data.get("access_token")
        advertiser_ids = data.get("advertiser_ids", [])
        advertiser_id = advertiser_ids[0] if advertiser_ids else ""
        if not access_token:
            return {"success": False, "error": "No access token in response"}
        existing = db.query(TikTokTokenModel).first()
        if existing:
            existing.access_token = access_token
            existing.advertiser_id = advertiser_id
            existing.advertiser_ids = json.dumps(advertiser_ids)
            existing.updated_at = datetime.utcnow()
        else:
            db.add(TikTokTokenModel(access_token=access_token, advertiser_id=advertiser_id, advertiser_ids=json.dumps(advertiser_ids)))
        db.commit()
        db.add(ActivityLogModel(action="TIKTOK_CONNECTED", entity_type="tiktok", details=f"Connected. Advertiser ID: {advertiser_id}"))
        db.commit()
        return {"success": True, "advertiser_id": advertiser_id, "advertiser_ids": advertiser_ids, "_token": access_token}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/status", summary="Check TikTok Status")
def check_tiktok_status(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"connected": False, "message": "No TikTok token found"}
    try:
        result = _tiktok_api("GET", "/oauth2/advertiser/get/", creds["access_token"],
                            params={"app_id": TIKTOK_APP_ID, "secret": TIKTOK_APP_SECRET})
        if result.get("code") == 0:
            return {"connected": True, "advertiser_id": creds["advertiser_id"],
                    "advertisers": result.get("data", {}).get("list", []), "message": "Connected"}
        return {"connected": False, "message": result.get("message", "API error")}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@router.post("/launch-campaign", summary="Launch TikTok Ad Campaign")
def launch_campaign(daily_budget: float = Query(20.0), campaign_name: str = Query("Court Sportswear - Tennis Apparel"), db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected."}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    results = {"steps": []}
    adgroup_budget = max(daily_budget, 20.0)
    schedule_start = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        camp_result = _tiktok_api("POST", "/campaign/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_name": campaign_name,
            "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE", "operation_status": "ENABLE",
        })
        results["steps"].append({"step": "create_campaign", "result": camp_result})
        if camp_result.get("code") != 0:
            return {"success": False, "error": camp_result.get("message"), "details": results}
        campaign_id = camp_result.get("data", {}).get("campaign_id")

        ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_id": campaign_id,
            "adgroup_name": f"{campaign_name} - Tennis Enthusiasts 25-55",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC", "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY", "budget": adgroup_budget,
            "schedule_type": "SCHEDULE_FROM_NOW", "schedule_start_time": schedule_start,
            "billing_event": "CPC", "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID", "pacing": "PACING_MODE_SMOOTH", "operation_status": "ENABLE",
            "location_ids": ["6252001"], "gender": "GENDER_UNLIMITED",
            "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        })
        results["steps"].append({"step": "create_adgroup", "result": ag_result})
        if ag_result.get("code") != 0:
            return {"success": False, "error": ag_result.get("message"), "details": results}
        adgroup_id = ag_result.get("data", {}).get("adgroup_id")

        # Upload image
        image_id = ""
        for img_url in _get_product_images()[:3]:
            image_id = _upload_image(access_token, advertiser_id, img_url)
            results["steps"].append({"step": "upload_image", "url": img_url, "image_id": image_id})
            if image_id:
                break

        identity = _find_best_identity(access_token, advertiser_id)
        results["steps"].append({"step": "find_identity", "result": identity})

        # Try video generation from image
        video_id = ""
        if image_id:
            video_id = _generate_video_from_image(access_token, advertiser_id, image_id)
            results["steps"].append({"step": "generate_video", "video_id": video_id})

        ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id, image_id, identity, video_id)
        results["steps"].append({"step": "create_ad", "result": ad_result})

        ad_id = None
        ad_warning = None
        if ad_result.get("success"):
            ad_ids = ad_result.get("ad_ids", [])
            ad_id = ad_ids[0] if ad_ids else None
        else:
            ad_warning = "Ad creation failed after multiple strategies. Campaign & ad group are live."

        db.add(CampaignModel(platform="tiktok", platform_campaign_id=str(campaign_id),
                             name=campaign_name, status="ACTIVE", campaign_type="TRAFFIC", daily_budget=adgroup_budget))
        db.add(ActivityLogModel(action="TIKTOK_CAMPAIGN_LAUNCHED", entity_type="campaign", entity_id=str(campaign_id),
                                details=f"Campaign: {campaign_id}, AdGroup: {adgroup_id}, Ad: {ad_id}"))
        db.commit()
        response = {"success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id, "ad_id": ad_id,
                    "daily_budget": adgroup_budget, "details": results}
        if ad_warning:
            response["ad_warning"] = ad_warning
        return response
    except Exception as e:
        return {"success": False, "error": str(e), "details": results}


@router.post("/create-ad-for-adgroup", summary="Create ad for existing ad group")
def create_ad_for_adgroup(adgroup_id: str = Query(...), image_url: str = Query(None), db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    results = {"steps": []}

    # Upload image
    image_urls = [image_url] if image_url else _get_product_images()
    image_id = ""
    for img_url in image_urls[:3]:
        image_id = _upload_image(access_token, advertiser_id, img_url)
        results["steps"].append({"step": "upload_image", "url": img_url, "image_id": image_id})
        if image_id:
            break
    if not image_id:
        existing = _get_existing_images(access_token, advertiser_id)
        if existing:
            image_id = existing[0].get("image_id", "")
            results["steps"].append({"step": "fallback_library", "image_id": image_id})
    if not image_id:
        return {"success": False, "error": "No images available", "details": results}

    # Find identity
    identity = _find_best_identity(access_token, advertiser_id)
    results["steps"].append({"step": "identity", "result": identity})
    if not identity.get("identity_id"):
        return {"success": False, "error": "No identity found", "details": results}

    # Try video generation
    video_id = _generate_video_from_image(access_token, advertiser_id, image_id)
    results["steps"].append({"step": "generate_video", "video_id": video_id})

    # Try multiple strategies
    ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id, image_id, identity, video_id)
    results["steps"].append({"step": "create_ad", "result": ad_result})

    if ad_result.get("success"):
        ad_ids = ad_result.get("ad_ids", [])
        return {"success": True, "ad_id": ad_ids[0] if ad_ids else None,
                "identity": identity, "image_id": image_id, "video_id": video_id, "details": results}
    return {"success": False, "error": "All ad creation strategies failed", "details": results}


@router.get("/images", summary="List uploaded images")
def list_images(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    images = _get_existing_images(creds["access_token"], creds["advertiser_id"])
    return {"count": len(images), "images": images}


@router.get("/identities", summary="List all TikTok identities")
def list_identities(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    all_identities = {}
    for it in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"], "identity_type": it})
        identities = result.get("data", {}).get("identity_list", []) if result.get("code") == 0 else []
        all_identities[it] = {"count": len(identities), "list": identities}
    return {"advertiser_id": creds["advertiser_id"], "identities": all_identities}


@router.get("/debug-image-upload", summary="Test image upload")
def debug_image_upload(image_url: str = Query(PRODUCT_IMAGES[0]), db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("POST", "/file/image/ad/upload/", creds["access_token"], data={
        "advertiser_id": creds["advertiser_id"], "upload_type": "UPLOAD_BY_URL", "image_url": image_url,
    })
    return {"image_url": image_url, "result": result}


@router.get("/performance", summary="Get TikTok Performance Data")
def get_tiktok_performance(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"error": "TikTok not connected"}
    try:
        result = _tiktok_api("GET", "/campaign/get/", creds["access_token"],
                           params={"advertiser_id": creds["advertiser_id"], "page_size": 100})
        campaigns = []
        total_spend = total_impressions = total_clicks = 0
        if result.get("code") == 0:
            for camp in result.get("data", {}).get("list", []):
                campaigns.append({"id": camp.get("campaign_id"), "name": camp.get("campaign_name"),
                                  "status": camp.get("operation_status"), "budget": camp.get("budget", 0),
                                  "objective": camp.get("objective_type")})
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        stats = _tiktok_api("GET", "/report/integrated/get/", creds["access_token"], params={
            "advertiser_id": creds["advertiser_id"], "report_type": "BASIC",
            "dimensions": json.dumps(["campaign_id"]), "data_level": "AUCTION_CAMPAIGN",
            "start_date": start_date, "end_date": end_date,
            "metrics": json.dumps(["spend", "impressions", "clicks", "ctr", "cpc", "reach"]),
        })
        if stats.get("code") == 0:
            for row in stats.get("data", {}).get("list", []):
                m = row.get("metrics", {})
                total_spend += float(m.get("spend", 0))
                total_impressions += int(m.get("impressions", 0))
                total_clicks += int(m.get("clicks", 0))
        return {"summary": {"total_campaigns": len(campaigns), "total_spend": round(total_spend, 2),
                            "total_impressions": total_impressions, "total_clicks": total_clicks,
                            "avg_ctr": round((total_clicks / total_impressions * 100) if total_impressions else 0, 2),
                            "avg_cpc": round((total_spend / total_clicks) if total_clicks else 0, 2)},
                "campaigns": campaigns}
    except Exception as e:
        return {"error": str(e)}


@router.get("/advertiser-info", summary="Get advertiser info")
def get_advertiser_info(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"error": "TikTok not connected"}
    return _tiktok_api("GET", "/advertiser/info/", creds["access_token"],
                       params={"advertiser_ids": json.dumps([creds["advertiser_id"]])})
