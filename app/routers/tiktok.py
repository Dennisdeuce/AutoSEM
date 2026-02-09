"""TikTok Ads router - OAuth, campaign creation, and performance tracking"""

import os
import json
import logging
import time
from datetime import datetime

import requests
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, TikTokTokenModel, CampaignModel, ActivityLogModel

logger = logging.getLogger("AutoSEM.TikTok")
router = APIRouter()

# TikTok App credentials
TIKTOK_APP_ID = os.environ.get("TIKTOK_APP_ID", "7602833892719542273")
TIKTOK_APP_SECRET = os.environ.get("TIKTOK_APP_SECRET", "b2d479247984871ef1b6f26c1639bf36ad822c21")
TIKTOK_REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "https://auto-sem.replit.app/api/v1/tiktok/callback")
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def _get_active_token(db: Session) -> dict:
    """Get the active TikTok access token and advertiser_id from DB."""
    token_record = db.query(TikTokTokenModel).first()
    if token_record and token_record.access_token:
        return {
            "access_token": token_record.access_token,
            "advertiser_id": token_record.advertiser_id,
        }
    return {"access_token": os.environ.get("TIKTOK_ACCESS_TOKEN", ""), "advertiser_id": os.environ.get("TIKTOK_ADVERTISER_ID", "")}


def _tiktok_api(method: str, endpoint: str, access_token: str, params: dict = None, data: dict = None) -> dict:
    """Make a TikTok Business API call."""
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


@router.get("/connect", summary="Connect TikTok",
            description="Redirect to TikTok OAuth authorization")
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


@router.get("/callback", summary="OAuth Callback",
            description="Handle TikTok OAuth callback")
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
        return HTMLResponse(content="<h1>Error</h1><p>No auth code received. Check URL for auth_code parameter.</p>")
    result = _exchange_token(the_code, db)
    if result.get("success"):
        adv_id = result.get('advertiser_id', 'unknown')
        html = f"""<h1>TikTok Connected!</h1>
        <p>Access token saved. Advertiser ID: {adv_id}</p>
        <p>Redirecting to dashboard...</p>
        <script>setTimeout(() => window.location='/dashboard', 3000)</script>"""
        return HTMLResponse(content=html)
    else:
        return HTMLResponse(content=f"<h1>Error</h1><p>{result.get('error', 'Unknown error')}</p>")


@router.post("/exchange-token", summary="Exchange auth code for access token")
def exchange_token_endpoint(
    auth_code: str = Query(...),
    db: Session = Depends(get_db),
):
    return _exchange_token(auth_code, db)


def _exchange_token(auth_code: str, db: Session) -> dict:
    """Exchange an auth_code for an access token."""
    try:
        url = f"{TIKTOK_API_BASE}/oauth2/access_token/"
        payload = {
            "app_id": TIKTOK_APP_ID,
            "secret": TIKTOK_APP_SECRET,
            "auth_code": auth_code,
        }
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
        return {"success": True, "advertiser_id": advertiser_id, "advertiser_ids": advertiser_ids}

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
            return {
                "connected": True,
                "advertiser_id": creds["advertiser_id"],
                "advertisers": advertisers,
                "message": "Connected"
            }
        return {"connected": False, "message": result.get("message", "API error")}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@router.post("/launch-campaign", summary="Launch TikTok Ad Campaign",
             description="Create a complete TikTok ad campaign with ad group and ads. "
                         "TikTok minimum: $50/day campaign budget, $20/day ad group budget.")
def launch_campaign(
    daily_budget: float = Query(20.0, description="Daily budget in USD (TikTok min: $20 ad group, $50 campaign)"),
    campaign_name: str = Query("Court Sportswear - Tennis Apparel", description="Campaign name"),
    db: Session = Depends(get_db),
):
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected. Visit /api/v1/tiktok/connect first."}

    access_token = creds["access_token"]
    advertiser_id = creds["advertiser_id"]
    results = {"steps": []}

    # TikTok enforces minimum budgets
    campaign_budget = max(daily_budget, 50.0)  # Campaign min: $50/day
    adgroup_budget = max(daily_budget, 20.0)    # Ad group min: $20/day

    try:
        # ── Step 1: Create Campaign (no budget limit, control at ad group level) ──
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
            # Fallback: try with explicit $50 budget
            campaign_data["budget_mode"] = "BUDGET_MODE_DAY"
            campaign_data["budget"] = campaign_budget
            camp_result = _tiktok_api("POST", "/campaign/create/", access_token, data=campaign_data)
            results["steps"].append({"step": "create_campaign_retry", "result": camp_result})
            if camp_result.get("code") != 0:
                return {"success": False, "error": f"Campaign creation failed: {camp_result.get('message')}", "details": results}

        campaign_id = camp_result.get("data", {}).get("campaign_id")
        logger.info(f"Campaign created: {campaign_id}")

        # ── Step 2: Create Ad Group with budget control ──
        adgroup_data = {
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": f"{campaign_name} - Tennis Enthusiasts 25-55",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": adgroup_budget,
            "schedule_type": "SCHEDULE_FROM_NOW",
            "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE",
            "location_ids": ["6252001"],  # United States
            "gender": "GENDER_UNLIMITED",
            "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        }
        ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data=adgroup_data)
        results["steps"].append({"step": "create_adgroup", "result": ag_result})

        if ag_result.get("code") != 0:
            # Retry with minimal targeting
            adgroup_data_simple = {
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id,
                "adgroup_name": f"{campaign_name} - Auto Targeting",
                "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
                "budget_mode": "BUDGET_MODE_DAY",
                "budget": adgroup_budget,
                "schedule_type": "SCHEDULE_FROM_NOW",
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

        # ── Step 3: Upload image and create ad ──
        product_images = [
            "https://court-sportswear.com/cdn/shop/files/unisex-organic-cotton-t-shirt-black-front-2-6783d1ce12e89.png",
            "https://court-sportswear.com/cdn/shop/files/all-over-print-recycled-unisex-sports-jersey-white-front-2-6783c7c53d88f.png",
        ]

        image_id = None
        for img_url in product_images:
            upload_data = {
                "advertiser_id": advertiser_id,
                "image_url": img_url,
            }
            img_result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data=upload_data)
            results["steps"].append({"step": "upload_image", "url": img_url, "result": img_result})
            if img_result.get("code") == 0:
                image_id = img_result.get("data", {}).get("image_id")
                logger.info(f"Image uploaded: {image_id}")
                break

        # Create ad
        ad_data = {
            "advertiser_id": advertiser_id,
            "adgroup_id": adgroup_id,
            "creatives": [{
                "ad_name": "Court Sportswear - Tennis & Pickleball Gear",
                "ad_text": "Premium tennis & pickleball apparel. Performance caps, polos & more. Shop now! \ud83c\udfbe",
                "landing_page_url": "https://court-sportswear.com/collections/all",
                "call_to_action": "SHOP_NOW",
                "ad_format": "SINGLE_IMAGE",
            }],
            "operation_status": "ENABLE",
        }
        if image_id:
            ad_data["creatives"][0]["image_ids"] = [image_id]

        ad_result = _tiktok_api("POST", "/ad/create/", access_token, data=ad_data)
        results["steps"].append({"step": "create_ad", "result": ad_result})

        ad_id = None
        if ad_result.get("code") == 0:
            ad_ids = ad_result.get("data", {}).get("ad_ids", [])
            ad_id = ad_ids[0] if ad_ids else None
            logger.info(f"Ad created: {ad_id}")

        # ── Step 4: Save to local database ──
        campaign_record = CampaignModel(
            platform="tiktok",
            platform_campaign_id=str(campaign_id),
            name=campaign_name,
            status="ACTIVE",
            campaign_type="TRAFFIC",
            daily_budget=adgroup_budget,
        )
        db.add(campaign_record)

        log = ActivityLogModel(
            action="TIKTOK_CAMPAIGN_LAUNCHED",
            entity_type="campaign",
            entity_id=str(campaign_id),
            details=f"Launched TikTok campaign '{campaign_name}' with ${adgroup_budget}/day budget. Campaign: {campaign_id}, Ad Group: {adgroup_id}, Ad: {ad_id}",
        )
        db.add(log)
        db.commit()

        return {
            "success": True,
            "campaign_id": campaign_id,
            "adgroup_id": adgroup_id,
            "ad_id": ad_id,
            "daily_budget": adgroup_budget,
            "note": f"TikTok minimum daily budget is $20/ad group. Budget set to ${adgroup_budget}/day.",
            "message": f"TikTok campaign launched! Campaign ID: {campaign_id}, Budget: ${adgroup_budget}/day",
            "details": results,
        }

    except Exception as e:
        logger.error(f"Campaign launch failed: {e}")
        return {"success": False, "error": str(e), "details": results}


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
                    "id": camp.get("campaign_id"),
                    "name": camp.get("campaign_name"),
                    "status": camp.get("operation_status"),
                    "budget": camp.get("budget", 0),
                    "objective": camp.get("objective_type"),
                })

        from datetime import timedelta
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        stats_result = _tiktok_api("GET", "/report/integrated/get/", creds["access_token"],
                                  params={
                                      "advertiser_id": creds["advertiser_id"],
                                      "report_type": "BASIC",
                                      "dimensions": json.dumps(["campaign_id"]),
                                      "data_level": "AUCTION_CAMPAIGN",
                                      "start_date": start_date,
                                      "end_date": end_date,
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
                "total_campaigns": len(campaigns),
                "total_spend": round(total_spend, 2),
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "avg_ctr": round(avg_ctr, 2),
                "avg_cpc": round(avg_cpc, 2),
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
