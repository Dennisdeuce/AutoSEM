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

# Current working product image URLs from Shopify CDN
PRODUCT_IMAGES = [
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-tennis-hoodie-921535.jpg?v=1708170515",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-tennis-hoodie-404401.jpg?v=1708087650",
    "https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-performance-crew-neck-tennis-t-shirt-999403.jpg?v=1707157727",
]


def _get_active_token(db: Session) -> dict:
    """Get TikTok token from DB first, then fall back to env vars (Replit Secrets)."""
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
    """Find the best available identity for ad creation.
    Priority: TT_USER (linked TikTok account) > BC_AUTH_TT > CUSTOMIZED_USER (deprecated)
    """
    for identity_type in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", access_token,
                             params={"advertiser_id": advertiser_id, "identity_type": identity_type})
        if result.get("code") == 0:
            identities = result.get("data", {}).get("identity_list", [])
            if identities:
                identity = identities[0]
                logger.info(f"Found identity type={identity_type}, id={identity.get('identity_id')}")
                return {"identity_id": identity.get("identity_id"), "identity_type": identity_type}
    logger.warning("No usable identity found")
    return {}


def _upload_image(access_token: str, advertiser_id: str, image_url: str) -> str:
    """Upload an image to TikTok via URL."""
    upload_data = {
        "advertiser_id": advertiser_id,
        "upload_type": "UPLOAD_BY_URL",
        "image_url": image_url,
    }
    result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data=upload_data)
    if result.get("code") == 0:
        image_id = result.get("data", {}).get("image_id", "")
        if image_id:
            logger.info(f"Image uploaded via URL: {image_id}")
            return image_id
    logger.warning(f"Image upload failed for {image_url}: {result.get('message')}")
    return ""


def _get_product_images(access_token: str, advertiser_id: str) -> list:
    """Try to fetch fresh product images from Shopify, fall back to constants."""
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
    except Exception as e:
        logger.warning(f"Failed to fetch Shopify products: {e}")
    return PRODUCT_IMAGES


@router.get("/connect", summary="Connect TikTok")
def connect_tiktok():
    if not TIKTOK_APP_ID:
        return {"error": "TIKTOK_APP_ID not configured"}
    auth_url = (
        f"https://business-api.tiktok.com/portal/auth"
        f"?app_id={TIKTOK_APP_ID}"
        f"&state=autosem_connect"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
    )
    return RedirectResponse(url=auth_url)


@router.get("/callback", summary="OAuth Callback")
def oauth_callback(
    auth_code: str = Query(None),
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db: Session = Depends(get_db),
):
    the_code = auth_code or code
    if error:
        return HTMLResponse(content=f"<h1>Error</h1><p>{error}</p>")
    if not the_code:
        return HTMLResponse(content="<h1>Error</h1><p>No auth code received.</p>")
    result = _exchange_token(the_code, db)
    if result.get("success"):
        adv_id = result.get("advertiser_id", "unknown")
        token = result.get("_token", "")
        html = '<!DOCTYPE html><html><head><title>TikTok Connected</title>'
        html += '<style>'
        html += 'body{font-family:Segoe UI,sans-serif;max-width:700px;margin:40px auto;padding:20px;background:#f5f5f5}'
        html += '.card{background:white;border-radius:12px;padding:30px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:20px}'
        html += 'h1{color:#28a745}'
        html += '.secret-box{background:#1e1e1e;color:#4ec9b0;padding:14px 18px;border-radius:8px;font-family:monospace;font-size:.85em;word-break:break-all;margin:8px 0;position:relative}'
        html += '.copy-btn{position:absolute;top:8px;right:8px;background:#4338ca;color:white;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.8em}'
        html += '.step{padding:12px 16px;background:#f0fdf4;border-left:4px solid #28a745;border-radius:4px;margin:10px 0}'
        html += '.warn{padding:12px 16px;background:#fef3c7;border-left:4px solid #f59e0b;border-radius:4px;margin:10px 0}'
        html += '</style></head><body>'
        html += '<div class="card"><h1>TikTok Connected!</h1>'
        html += f'<p>Advertiser ID: <strong>{adv_id}</strong></p>'
        html += '<p>Token saved to database. To <strong>persist across deploys</strong>, add these as Replit Secrets:</p></div>'
        html += '<div class="card"><h2>Add These Replit Secrets</h2>'
        html += '<div class="step"><strong>Step 1:</strong> In Replit, go to Secrets (lock icon in sidebar)</div>'
        html += '<p><strong>TIKTOK_ACCESS_TOKEN</strong></p>'
        html += f'<div class="secret-box" id="tb">{token}<button class="copy-btn" onclick="copyT(\'tb\')">Copy</button></div>'
        html += '<p><strong>TIKTOK_ADVERTISER_ID</strong></p>'
        html += f'<div class="secret-box" id="ab">{adv_id}<button class="copy-btn" onclick="copyT(\'ab\')">Copy</button></div>'
        html += '<div class="step"><strong>Step 2:</strong> Republish after adding secrets. Token survives all future deploys.</div>'
        html += '<div class="warn">This is the LAST TIME you need to authorize. Once secrets are saved, you are set permanently.</div></div>'
        html += '<div class="card"><a href="/dashboard" style="font-size:1.1em">Go to Dashboard</a></div>'
        html += '<script>function copyT(id){var e=document.getElementById(id);var t=e.textContent.replace("Copy","").trim();navigator.clipboard.writeText(t);e.querySelector(".copy-btn").textContent="Copied!";setTimeout(function(){e.querySelector(".copy-btn").textContent="Copy"},2000)}</script>'
        html += '</body></html>'
        return HTMLResponse(content=html)
    else:
        return HTMLResponse(content=f"<h1>Error</h1><p>{result.get('error', 'Unknown error')}</p>")


@router.post("/exchange-token", summary="Exchange auth code for access token")
def exchange_token_endpoint(auth_code: str = Query(...), db: Session = Depends(get_db)):
    return _exchange_token(auth_code, db)


def _exchange_token(auth_code: str, db: Session) -> dict:
    try:
        url = f"{TIKTOK_API_BASE}/oauth2/access_token/"
        payload = {"app_id": TIKTOK_APP_ID, "secret": TIKTOK_APP_SECRET, "auth_code": auth_code}
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"TikTok token exchange response: {json.dumps(result, indent=2)}")

        if result.get("code") != 0:
            return {"success": False, "error": result.get("message", "Token exchange failed"), "raw": result}

        data = result.get("data", {})
        access_token = data.get("access_token")
        advertiser_ids = data.get("advertiser_ids", [])
        advertiser_id = advertiser_ids[0] if advertiser_ids else ""

        if not access_token:
            return {"success": False, "error": "No access token in response", "raw": result}

        existing = db.query(TikTokTokenModel).first()
        if existing:
            existing.access_token = access_token
            existing.advertiser_id = advertiser_id
            existing.advertiser_ids = json.dumps(advertiser_ids)
            existing.updated_at = datetime.utcnow()
        else:
            token_record = TikTokTokenModel(
                access_token=access_token,
                advertiser_id=advertiser_id,
                advertiser_ids=json.dumps(advertiser_ids),
            )
            db.add(token_record)
        db.commit()

        log = ActivityLogModel(
            action="TIKTOK_CONNECTED",
            entity_type="tiktok",
            details=f"Connected TikTok. Advertiser ID: {advertiser_id}",
        )
        db.add(log)
        db.commit()

        logger.info(f"TikTok token saved. Advertiser ID: {advertiser_id}")
        return {"success": True, "advertiser_id": advertiser_id, "advertiser_ids": advertiser_ids, "_token": access_token}

    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
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
            advertisers = result.get("data", {}).get("list", [])
            return {"connected": True, "advertiser_id": creds["advertiser_id"], "advertisers": advertisers, "message": "Connected"}
        return {"connected": False, "message": result.get("message", "API error")}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@router.post("/launch-campaign", summary="Launch TikTok Ad Campaign")
def launch_campaign(
    daily_budget: float = Query(20.0, description="Daily budget in USD (TikTok min: $20 ad group)"),
    campaign_name: str = Query("Court Sportswear - Tennis Apparel", description="Campaign name"),
    db: Session = Depends(get_db),
):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected. Visit /api/v1/tiktok/connect first."}

    access_token = creds["access_token"]
    advertiser_id = creds["advertiser_id"]
    results = {"steps": []}
    adgroup_budget = max(daily_budget, 20.0)
    schedule_start = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Step 1: Create Campaign
        campaign_data = {
            "advertiser_id": advertiser_id,
            "campaign_name": campaign_name,
            "objective_type": "TRAFFIC",
            "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE",
        }
        camp_result = _tiktok_api("POST", "/campaign/create/", access_token, data=campaign_data)
        results["steps"].append({"step": "create_campaign", "result": camp_result})

        if camp_result.get("code") != 0:
            campaign_data["budget_mode"] = "BUDGET_MODE_DAY"
            campaign_data["budget"] = 50.0
            camp_result = _tiktok_api("POST", "/campaign/create/", access_token, data=campaign_data)
            results["steps"].append({"step": "create_campaign_retry", "result": camp_result})
            if camp_result.get("code") != 0:
                return {"success": False, "error": f"Campaign creation failed: {camp_result.get('message')}", "details": results}

        campaign_id = camp_result.get("data", {}).get("campaign_id")
        logger.info(f"Campaign created: {campaign_id}")

        # Step 2: Create Ad Group
        adgroup_data = {
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": f"{campaign_name} - Tennis Enthusiasts 25-55",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
            "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": adgroup_budget,
            "schedule_type": "SCHEDULE_FROM_NOW",
            "schedule_start_time": schedule_start,
            "billing_event": "CPC",
            "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE",
            "location_ids": ["6252001"],
            "gender": "GENDER_UNLIMITED",
            "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        }
        ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data=adgroup_data)
        results["steps"].append({"step": "create_adgroup", "result": ag_result})

        if ag_result.get("code") != 0:
            adgroup_data_simple = {
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id,
                "adgroup_name": f"{campaign_name} - Auto Targeting",
                "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
                "promotion_type": "WEBSITE",
                "budget_mode": "BUDGET_MODE_DAY",
                "budget": adgroup_budget,
                "schedule_type": "SCHEDULE_FROM_NOW",
                "schedule_start_time": schedule_start,
                "billing_event": "OCPM",
                "optimization_goal": "CLICK",
                "bid_type": "BID_TYPE_NO_BID",
                "pacing": "PACING_MODE_SMOOTH",
                "operation_status": "ENABLE",
                "location_ids": ["6252001"],
            }
            ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data=adgroup_data_simple)
            results["steps"].append({"step": "create_adgroup_retry", "result": ag_result})
            if ag_result.get("code") != 0:
                return {"success": False, "error": f"Ad group creation failed: {ag_result.get('message')}", "details": results}

        adgroup_id = ag_result.get("data", {}).get("adgroup_id")
        logger.info(f"Ad group created: {adgroup_id}")

        # Step 3: Upload product image (dynamic from Shopify)
        product_images = _get_product_images(access_token, advertiser_id)
        image_id = ""
        for img_url in product_images[:3]:
            image_id = _upload_image(access_token, advertiser_id, img_url)
            results["steps"].append({"step": "upload_image", "url": img_url, "image_id": image_id})
            if image_id:
                break

        # Step 4: Find best identity
        identity = _find_best_identity(access_token, advertiser_id)
        results["steps"].append({"step": "find_identity", "result": identity})
        identity_id = identity.get("identity_id", "")
        identity_type = identity.get("identity_type", "")

        # Step 5: Create Ad
        ad_creative = {
            "ad_name": "Court Sportswear - Tennis & Pickleball Gear",
            "ad_text": "Premium tennis & pickleball apparel. Performance caps, polos & more. Shop now!",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_IMAGE",
        }
        if identity_id:
            ad_creative["identity_id"] = identity_id
            ad_creative["identity_type"] = identity_type
        if image_id:
            ad_creative["image_ids"] = [image_id]

        ad_data = {
            "advertiser_id": advertiser_id,
            "adgroup_id": adgroup_id,
            "creatives": [ad_creative],
            "operation_status": "ENABLE",
        }
        ad_result = _tiktok_api("POST", "/ad/create/", access_token, data=ad_data)
        results["steps"].append({"step": "create_ad", "result": ad_result})

        ad_id = None
        ad_warning = None
        if ad_result.get("code") == 0:
            ad_ids = ad_result.get("data", {}).get("ad_ids", [])
            ad_id = ad_ids[0] if ad_ids else None
        else:
            ad_warning = f"Ad creation failed: {ad_result.get('message')}. Campaign and ad group are live."

        # Save to local DB
        campaign_record = CampaignModel(
            platform="tiktok", platform_campaign_id=str(campaign_id),
            name=campaign_name, status="ACTIVE", campaign_type="TRAFFIC", daily_budget=adgroup_budget,
        )
        db.add(campaign_record)
        log = ActivityLogModel(
            action="TIKTOK_CAMPAIGN_LAUNCHED", entity_type="campaign", entity_id=str(campaign_id),
            details=f"Launched TikTok campaign '{campaign_name}' ${adgroup_budget}/day. Campaign: {campaign_id}, AdGroup: {adgroup_id}, Ad: {ad_id}",
        )
        db.add(log)
        db.commit()

        response = {
            "success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id, "ad_id": ad_id,
            "daily_budget": adgroup_budget,
            "message": f"TikTok campaign launched! Campaign ID: {campaign_id}, Budget: ${adgroup_budget}/day",
            "details": results,
        }
        if ad_warning:
            response["ad_warning"] = ad_warning
        return response

    except Exception as e:
        logger.error(f"Campaign launch failed: {e}")
        return {"success": False, "error": str(e), "details": results}


@router.post("/create-ad-for-adgroup", summary="Create ad for existing ad group")
def create_ad_for_adgroup(
    adgroup_id: str = Query(..., description="Existing ad group ID"),
    image_url: str = Query(None, description="Optional image URL override"),
    db: Session = Depends(get_db),
):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected"}

    access_token = creds["access_token"]
    advertiser_id = creds["advertiser_id"]
    results = {"steps": []}

    # Upload image - use provided URL or fetch from Shopify
    if image_url:
        image_urls = [image_url]
    else:
        image_urls = _get_product_images(access_token, advertiser_id)

    image_id = ""
    for img_url in image_urls[:3]:
        image_id = _upload_image(access_token, advertiser_id, img_url)
        results["steps"].append({"step": "upload_image", "url": img_url, "image_id": image_id})
        if image_id:
            break

    if not image_id:
        return {"success": False, "error": "All image uploads failed", "details": results}

    # Find identity
    identity = _find_best_identity(access_token, advertiser_id)
    results["steps"].append({"step": "identity", "result": identity})
    identity_id = identity.get("identity_id", "")
    identity_type = identity.get("identity_type", "")

    if not identity_id:
        return {"success": False, "error": "No usable identity found. Link a TikTok account in TikTok Ads Manager.", "details": results}

    # Create ad
    ad_creative = {
        "ad_name": "Court Sportswear - Tennis & Pickleball Gear",
        "ad_text": "Premium tennis & pickleball apparel. Performance caps, polos & more. Shop now!",
        "landing_page_url": "https://court-sportswear.com/collections/all",
        "call_to_action": "SHOP_NOW",
        "ad_format": "SINGLE_IMAGE",
        "identity_id": identity_id,
        "identity_type": identity_type,
        "image_ids": [image_id],
    }

    ad_data = {
        "advertiser_id": advertiser_id,
        "adgroup_id": adgroup_id,
        "creatives": [ad_creative],
        "operation_status": "ENABLE",
    }
    ad_result = _tiktok_api("POST", "/ad/create/", access_token, data=ad_data)
    results["steps"].append({"step": "create_ad", "result": ad_result})

    if ad_result.get("code") == 0:
        ad_ids = ad_result.get("data", {}).get("ad_ids", [])
        ad_id = ad_ids[0] if ad_ids else None
        return {"success": True, "ad_id": ad_id, "identity_id": identity_id, "image_id": image_id, "details": results}

    return {"success": False, "error": ad_result.get("message", "Ad creation failed"), "details": results}


@router.get("/identities", summary="List all TikTok identities")
def list_identities(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}

    all_identities = {}
    for identity_type in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"], "identity_type": identity_type})
        identities = []
        if result.get("code") == 0:
            identities = result.get("data", {}).get("identity_list", [])
        all_identities[identity_type] = {"count": len(identities), "list": identities}

    return {"advertiser_id": creds["advertiser_id"], "identities": all_identities}


@router.get("/debug-image-upload", summary="Test image upload")
def debug_image_upload(
    image_url: str = Query("https://cdn.shopify.com/s/files/1/0672/2030/8191/products/mens-tennis-hoodie-921535.jpg?v=1708170515"),
    db: Session = Depends(get_db),
):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}

    url_data = {
        "advertiser_id": creds["advertiser_id"],
        "upload_type": "UPLOAD_BY_URL",
        "image_url": image_url,
    }
    result = _tiktok_api("POST", "/file/image/ad/upload/", creds["access_token"], data=url_data)
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
        total_spend = 0
        total_impressions = 0
        total_clicks = 0

        if result.get("code") == 0:
            for camp in result.get("data", {}).get("list", []):
                campaigns.append({
                    "id": camp.get("campaign_id"), "name": camp.get("campaign_name"),
                    "status": camp.get("operation_status"), "budget": camp.get("budget", 0),
                    "objective": camp.get("objective_type"),
                })

        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        stats_result = _tiktok_api("GET", "/report/integrated/get/", creds["access_token"],
                                  params={
                                      "advertiser_id": creds["advertiser_id"],
                                      "report_type": "BASIC",
                                      "dimensions": json.dumps(["campaign_id"]),
                                      "data_level": "AUCTION_CAMPAIGN",
                                      "start_date": start_date, "end_date": end_date,
                                      "metrics": json.dumps(["spend", "impressions", "clicks", "ctr", "cpc", "reach"]),
                                  })
        if stats_result.get("code") == 0:
            for row in stats_result.get("data", {}).get("list", []):
                metrics = row.get("metrics", {})
                total_spend += float(metrics.get("spend", 0))
                total_impressions += int(metrics.get("impressions", 0))
                total_clicks += int(metrics.get("clicks", 0))

        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
        avg_cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
        return {
            "summary": {
                "total_campaigns": len(campaigns), "total_spend": round(total_spend, 2),
                "total_impressions": total_impressions, "total_clicks": total_clicks,
                "avg_ctr": round(avg_ctr, 2), "avg_cpc": round(avg_cpc, 2),
            },
            "campaigns": campaigns,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/advertiser-info", summary="Get advertiser info")
def get_advertiser_info(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"error": "TikTok not connected"}
    result = _tiktok_api("GET", "/advertiser/info/", creds["access_token"],
                        params={"advertiser_ids": json.dumps([creds["advertiser_id"]])})
    return result
