"""TikTok Ads router - OAuth, campaign creation, and performance tracking

Ad creation strategy priority (v0.3.5 - CUSTOMIZED_USER for non-Spark ads):
1. SINGLE_IMAGE + CUSTOMIZED_USER (non-Spark ad, no video needed)
2. SINGLE_IMAGE + CUSTOMIZED_USER without CTA (fallback)
3. SINGLE_VIDEO + CUSTOMIZED_USER (when video available)
4. SINGLE_VIDEO + display_name only
5. Pangle image ad (audience network, NO location_ids)

Identity types:
- CUSTOMIZED_USER: For regular in-feed ads (non-Spark). This is what we use.
- TT_USER: For Spark Ads ONLY (requires tiktok_item_id referencing existing post)
- BC_AUTH_TT: Business Center authorized accounts
"""

import os
import io
import json
import logging
import time
import tempfile
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

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


# ── Core Helpers ──

def _get_ffmpeg_path() -> str:
    """Find ffmpeg: system PATH -> imageio-ffmpeg bundle -> empty string."""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run([ffmpeg_exe, "-version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            logger.info(f"Using bundled ffmpeg: {ffmpeg_exe}")
            return ffmpeg_exe
    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"imageio-ffmpeg not available: {e}")
    return ""


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


def _tiktok_upload(endpoint: str, access_token: str, advertiser_id: str,
                   file_path: str, file_field: str = "video_file",
                   extra_data: dict = None) -> dict:
    """Upload a file to TikTok using multipart form data."""
    url = f"{TIKTOK_API_BASE}{endpoint}"
    headers = {"Access-Token": access_token}
    data = {"advertiser_id": advertiser_id}
    if extra_data:
        data.update(extra_data)
    try:
        with open(file_path, "rb") as f:
            files = {file_field: (os.path.basename(file_path), f, "video/mp4")}
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"TikTok upload error: {e}")
        return {"code": -1, "message": str(e)}


# ── Identity Management ──

def _find_best_identity(access_token: str, advertiser_id: str) -> dict:
    """Find best identity for NON-SPARK ad creation.

    For regular in-feed ads (non-Spark), CUSTOMIZED_USER is required.
    TT_USER is ONLY for Spark Ads (which need tiktok_item_id).

    Priority for non-Spark: CUSTOMIZED_USER > BC_AUTH_TT > TT_USER (last resort)
    """
    # Priority 1: CUSTOMIZED_USER (correct for non-Spark in-feed ads)
    result = _tiktok_api("GET", "/identity/get/", access_token,
                         params={"advertiser_id": advertiser_id, "identity_type": "CUSTOMIZED_USER"})
    if result.get("code") == 0:
        identities = result.get("data", {}).get("identity_list", [])
        if identities:
            ident = identities[0]
            logger.info(f"Using CUSTOMIZED_USER identity: {ident.get('identity_id')} (correct for non-Spark ads)")
            return {"identity_id": ident.get("identity_id"),
                    "identity_type": "CUSTOMIZED_USER",
                    "display_name": ident.get("display_name", "Court Sportswear"),
                    "profile_image": ident.get("profile_image", "")}

    # Priority 2: BC_AUTH_TT (Business Center authorized TikTok account)
    result = _tiktok_api("GET", "/identity/get/", access_token,
                         params={"advertiser_id": advertiser_id, "identity_type": "BC_AUTH_TT"})
    if result.get("code") == 0:
        identities = result.get("data", {}).get("identity_list", [])
        if identities:
            ident = identities[0]
            logger.info(f"Using BC_AUTH_TT identity: {ident.get('identity_id')}")
            return {"identity_id": ident.get("identity_id"),
                    "identity_type": "BC_AUTH_TT",
                    "display_name": ident.get("display_name", "Court Sportswear"),
                    "profile_image": ident.get("profile_image", "")}

    # Priority 3: TT_USER (last resort - mainly for Spark Ads, may fail for non-Spark)
    result = _tiktok_api("GET", "/identity/get/", access_token,
                         params={"advertiser_id": advertiser_id, "identity_type": "TT_USER"})
    if result.get("code") == 0:
        identities = result.get("data", {}).get("identity_list", [])
        if identities:
            ident = identities[0]
            logger.warning("Using TT_USER identity as last resort - may fail for non-Spark ads")
            return {"identity_id": ident.get("identity_id"),
                    "identity_type": "TT_USER",
                    "display_name": ident.get("display_name", "Court Sportswear"),
                    "profile_image": ident.get("profile_image", "")}

    return {}


# ── Image Management ──

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


def _upload_images(access_token: str, advertiser_id: str, image_urls: list) -> list:
    """Upload multiple images, return list of image_ids."""
    image_ids = []
    for url in image_urls:
        result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
            "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": url,
            "file_name": f"cs_{int(time.time())}_{len(image_ids)}.jpg",
        })
        if result.get("code") == 0:
            img_id = result.get("data", {}).get("image_id", "")
            if img_id:
                image_ids.append(img_id)
        elif result.get("code") == 40911:
            # Duplicate - try with unique name
            result2 = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
                "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": url,
                "file_name": f"cs_u{int(time.time())}_{len(image_ids)}.jpg",
            })
            if result2.get("code") == 0:
                img_id = result2.get("data", {}).get("image_id", "")
                if img_id:
                    image_ids.append(img_id)
    return image_ids


# ── Video Generation ──

def _create_minimal_mp4(image_paths: list, output_path: str, duration_per_image: int = 3) -> bool:
    """Create 9:16 vertical MP4 from images using ffmpeg."""
    ffmpeg_exe = _get_ffmpeg_path()
    if not ffmpeg_exe or not image_paths:
        return False
    try:
        list_path = output_path + ".txt"
        with open(list_path, "w") as f:
            for img in image_paths:
                f.write(f"file '{img}'\n")
                f.write(f"duration {duration_per_image}\n")
            f.write(f"file '{image_paths[-1]}'\n")
        cmd = [
            ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            "-movflags", "+faststart",
            "-t", str(len(image_paths) * duration_per_image), output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        try:
            os.remove(list_path)
        except Exception:
            pass
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            logger.info(f"Video created: {output_path} ({size} bytes)")
            return size > 1000
        logger.error(f"ffmpeg failed: {result.stderr.decode()[:500]}")
        return False
    except Exception as e:
        logger.error(f"Video creation error: {e}")
        return False


def _download_images_for_video(image_urls: list, max_images: int = 5) -> list:
    """Download product images to temp files for video creation."""
    paths = []
    for url in image_urls[:max_images]:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.write(resp.content)
                tmp.close()
                paths.append(tmp.name)
        except Exception as e:
            logger.warning(f"Failed to download {url}: {e}")
    return paths


def _generate_and_upload_video(access_token: str, advertiser_id: str,
                                image_urls: list = None) -> dict:
    """Full pipeline: download images -> create video -> upload to TikTok."""
    if not image_urls:
        image_urls = _get_product_images()[:5]
    steps = []

    image_paths = _download_images_for_video(image_urls)
    steps.append({"step": "download_images", "count": len(image_paths)})
    if not image_paths:
        return {"video_id": "", "steps": steps, "error": "No images downloaded"}

    video_path = tempfile.mktemp(suffix=".mp4")
    success = _create_minimal_mp4(image_paths, video_path, duration_per_image=3)
    steps.append({"step": "create_video", "success": success})

    for p in image_paths:
        try:
            os.remove(p)
        except Exception:
            pass

    if not success:
        return {"video_id": "", "steps": steps, "error": "Video creation failed (ffmpeg)"}

    video_id = ""
    try:
        result = _tiktok_upload(
            "/file/video/ad/upload/", access_token, advertiser_id,
            video_path, file_field="video_file",
            extra_data={"upload_type": "UPLOAD_BY_FILE",
                       "file_name": f"court_sportswear_{int(time.time())}.mp4"})
        steps.append({"step": "upload_video", "code": result.get("code"),
                      "message": result.get("message")})
        if result.get("code") == 0:
            video_id = result.get("data", {}).get("video_id", "")
    except Exception as e:
        steps.append({"step": "upload_video", "error": str(e)})

    try:
        os.remove(video_path)
    except Exception:
        pass

    return {"video_id": video_id, "steps": steps}


# ── Ad Creation ──

def _try_create_ad(access_token: str, advertiser_id: str, adgroup_id: str,
                   image_id: str, identity: dict, video_id: str = "",
                   campaign_id: str = "") -> dict:
    """Try multiple ad creation strategies in priority order.

    Key insight: CUSTOMIZED_USER is for regular in-feed ads (non-Spark).
    TT_USER is for Spark Ads ONLY and requires tiktok_item_id.
    Using TT_USER without tiktok_item_id causes "source of post invalid" (40002).

    Strategy 1: SINGLE_IMAGE + CUSTOMIZED_USER (primary - no video needed)
    Strategy 2: SINGLE_IMAGE + CUSTOMIZED_USER without CTA (CTA fallback)
    Strategy 3: SINGLE_VIDEO + CUSTOMIZED_USER (when video available)
    Strategy 4: SINGLE_VIDEO + display_name only
    Strategy 5: Pangle image ad (NO location_ids - avoids permission error)
    """
    identity_id = identity.get("identity_id", "")
    identity_type = identity.get("identity_type", "CUSTOMIZED_USER")
    display_name = identity.get("display_name", "Court Sportswear")
    attempts = []

    # ── Strategy 1: SINGLE_IMAGE + CUSTOMIZED_USER (non-Spark, no video needed) ──
    if image_id and identity_id:
        creative = {
            "ad_name": f"Court Sportswear - Tennis Apparel {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_IMAGE",
            "image_ids": [image_id],
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "image_customized_user", "code": result.get("code"),
                        "message": result.get("message"), "data": result.get("data"),
                        "identity_type_used": identity_type})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []),
                    "strategy": "image_customized_user", "attempts": attempts}

    # ── Strategy 2: SINGLE_IMAGE without call_to_action (CTA can cause issues) ──
    if image_id and identity_id:
        creative = {
            "ad_name": f"Court Sportswear - Performance Gear {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Shop court-sportswear.com",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "ad_format": "SINGLE_IMAGE",
            "image_ids": [image_id],
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "image_no_cta", "code": result.get("code"),
                        "message": result.get("message"), "data": result.get("data")})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []),
                    "strategy": "image_no_cta", "attempts": attempts}

    # ── Strategy 3: SINGLE_VIDEO + CUSTOMIZED_USER (TikTok's native format) ──
    if video_id and identity_id:
        creative = {
            "ad_name": f"Court Sportswear - Video Ad {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        if image_id:
            creative["image_ids"] = [image_id]  # thumbnail
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "video_customized_user", "code": result.get("code"),
                        "message": result.get("message"), "data": result.get("data")})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []),
                    "strategy": "video_customized_user", "attempts": attempts}

    # ── Strategy 4: SINGLE_VIDEO + display_name only ──
    if video_id:
        creative = {
            "ad_name": f"Court Sportswear - Tennis Video {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "display_name": display_name,
        }
        if image_id:
            creative["image_ids"] = [image_id]
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        attempts.append({"strategy": "video_display_name", "code": result.get("code"),
                        "message": result.get("message"), "data": result.get("data")})
        if result.get("code") == 0:
            return {"success": True, "ad_ids": result.get("data", {}).get("ad_ids", []),
                    "strategy": "video_display_name", "attempts": attempts}

    # ── Strategy 5: Pangle image ad (NO location_ids - avoids permission error) ──
    if image_id and campaign_id and identity_id:
        schedule_start = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        ag_result = _tiktok_api("POST", "/adgroup/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_id": campaign_id,
            "adgroup_name": f"Court Sportswear - Pangle Display {int(time.time()) % 10000}",
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_PANGLE"],
            "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY", "budget": 20.0,
            "schedule_type": "SCHEDULE_FROM_NOW", "schedule_start_time": schedule_start,
            "billing_event": "CPC", "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID", "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE",
            "gender": "GENDER_UNLIMITED",
            "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        })
        attempts.append({"strategy": "create_pangle_adgroup", "code": ag_result.get("code"),
                         "message": ag_result.get("message")})
        if ag_result.get("code") == 0:
            pangle_ag_id = ag_result.get("data", {}).get("adgroup_id")
            creative = {
                "ad_name": f"Court Sportswear - Pangle Image {int(time.time()) % 10000}",
                "ad_text": "Premium tennis & pickleball apparel. Shop now!",
                "landing_page_url": "https://court-sportswear.com/collections/all",
                "call_to_action": "SHOP_NOW",
                "ad_format": "SINGLE_IMAGE",
                "image_ids": [image_id],
                "identity_id": identity_id,
                "identity_type": identity_type,
            }
            ad_result = _tiktok_api("POST", "/ad/create/", access_token, data={
                "advertiser_id": advertiser_id, "adgroup_id": pangle_ag_id,
                "creatives": [creative], "operation_status": "ENABLE"})
            attempts.append({"strategy": "pangle_image_ad", "code": ad_result.get("code"),
                             "message": ad_result.get("message"), "adgroup_id": pangle_ag_id})
            if ad_result.get("code") == 0:
                return {"success": True, "ad_ids": ad_result.get("data", {}).get("ad_ids", []),
                        "pangle_adgroup_id": pangle_ag_id, "strategy": "pangle_image",
                        "attempts": attempts}

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
        return HTMLResponse(content=f'''<!DOCTYPE html><html><head><title>TikTok Connected</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:40px auto;padding:20px;background:#f5f5f5}}
.card{{background:white;border-radius:12px;padding:30px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
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
    """Full campaign launch: campaign -> ad group -> upload images -> generate video -> create ad."""
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected."}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []
    adgroup_budget = max(daily_budget, 20.0)

    try:
        # Step 1: Create campaign
        camp = _tiktok_api("POST", "/campaign/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_name": campaign_name,
            "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE"})
        steps.append({"step": "campaign", "code": camp.get("code"), "message": camp.get("message")})
        if camp.get("code") != 0:
            return {"success": False, "error": camp.get("message"), "steps": steps}
        campaign_id = camp["data"]["campaign_id"]

        # Step 2: Create ad group
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
            return {"success": False, "error": ag.get("message"), "steps": steps, "campaign_id": campaign_id}
        adgroup_id = ag["data"]["adgroup_id"]

        # Step 3: Upload product images
        product_urls = _get_product_images()[:5]
        image_ids = _upload_images(access_token, advertiser_id, product_urls)
        steps.append({"step": "upload_images", "count": len(image_ids)})

        # Step 4: Generate and upload video
        video_result = _generate_and_upload_video(access_token, advertiser_id, product_urls)
        video_id = video_result.get("video_id", "")
        steps.append({"step": "video_generation", "video_id": video_id,
                      "details": video_result.get("steps", [])})

        # Step 5: Find identity (CUSTOMIZED_USER preferred for non-Spark ads)
        identity = _find_best_identity(access_token, advertiser_id)
        steps.append({"step": "identity", "result": identity})

        # Step 6: Create ad (image first, video if available, pangle fallback)
        image_id = image_ids[0] if image_ids else ""
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
                                details=f"Campaign: {campaign_id}, AdGroup: {adgroup_id}, Ad: {ad_id}, Video: {video_id}, Strategy: {ad_result.get('strategy', 'none')}"))
        db.commit()

        return {"success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id,
                "ad_id": ad_id, "video_id": video_id, "daily_budget": adgroup_budget,
                "ad_strategy": ad_result.get("strategy"),
                "ad_warning": None if ad_id else "Ad creation pending - check steps",
                "steps": steps}
    except Exception as e:
        return {"success": False, "error": str(e), "steps": steps}


@router.post("/create-ad-for-adgroup", summary="Create ad for existing ad group")
def create_ad_for_adgroup(adgroup_id: str = Query(...),
                          campaign_id: str = Query("1856672017238274"),
                          image_url: str = Query(None),
                          db: Session = Depends(get_db)):
    """Create an ad for an existing ad group."""
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []

    # Upload images
    image_urls = [image_url] if image_url else _get_product_images()[:5]
    image_ids = _upload_images(access_token, advertiser_id, image_urls)
    steps.append({"step": "images", "count": len(image_ids), "ids": image_ids})

    # Generate video
    video_result = _generate_and_upload_video(access_token, advertiser_id, image_urls)
    video_id = video_result.get("video_id", "")
    steps.append({"step": "video", "video_id": video_id, "details": video_result.get("steps", [])})

    # Identity (CUSTOMIZED_USER preferred for non-Spark ads)
    identity = _find_best_identity(access_token, advertiser_id)
    steps.append({"step": "identity", "result": identity})
    if not identity.get("identity_id"):
        return {"success": False, "error": "No identity found. Create a CUSTOMIZED_USER identity in TikTok Ads Manager.", "steps": steps}

    # Try ad creation strategies
    image_id = image_ids[0] if image_ids else ""
    ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                image_id, identity, video_id, campaign_id)
    steps.append({"step": "create_ad", "result": ad_result})

    if ad_result.get("success"):
        return {"success": True, "ad_ids": ad_result.get("ad_ids", []),
                "strategy": ad_result.get("strategy"),
                "video_id": video_id, "steps": steps}
    return {"success": False, "error": "All strategies failed", "steps": steps}


# ── Video Upload Endpoints ──

@router.post("/generate-video", summary="Generate and upload video from product images")
def generate_video_endpoint(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    return _generate_and_upload_video(creds["access_token"], creds["advertiser_id"],
                                      _get_product_images()[:5])


@router.post("/upload-video-url", summary="Upload video from URL")
def upload_video_from_url(video_url: str = Query(...), db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("POST", "/file/video/ad/upload/", creds["access_token"], data={
        "advertiser_id": creds["advertiser_id"], "upload_type": "UPLOAD_BY_URL",
        "video_url": video_url, "file_name": f"court_sportswear_{int(time.time())}.mp4"})
    return {"result": result, "video_id": result.get("data", {}).get("video_id", "") if result.get("code") == 0 else ""}


# ── Debug & Info Endpoints ──

@router.get("/images", summary="List uploaded images")
def list_images(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/file/image/ad/get/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"], "page_size": 50})
    images = result.get("data", {}).get("list", []) if result.get("code") == 0 else []
    return {"count": len(images), "images": images,
            "raw_code": result.get("code"), "raw_message": result.get("message")}


@router.get("/videos", summary="List uploaded videos")
def list_videos(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/file/video/ad/get/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"], "page_size": 50})
    videos = result.get("data", {}).get("list", []) if result.get("code") == 0 else []
    return {"count": len(videos), "videos": videos,
            "raw_code": result.get("code"), "raw_message": result.get("message")}


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


@router.get("/debug-ffmpeg", summary="Check ffmpeg availability")
def debug_ffmpeg():
    info = {"system_ffmpeg": False, "bundled_ffmpeg": False, "resolved_path": ""}
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            info["system_ffmpeg"] = True
            info["system_version"] = result.stdout.decode()[:200]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run([ffmpeg_exe, "-version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            info["bundled_ffmpeg"] = True
            info["bundled_path"] = ffmpeg_exe
    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        info["bundled_error"] = str(e)
    info["resolved_path"] = _get_ffmpeg_path()
    info["available"] = bool(info["resolved_path"])
    return info


@router.get("/debug-slideshow", summary="Test slideshow creation")
def debug_slideshow(db: Session = Depends(get_db)):
    """Debug endpoint - test image upload and slideshow creation."""
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    image_urls = _get_product_images()[:5]
    image_ids = _upload_images(access_token, advertiser_id, image_urls)
    video_result = _generate_and_upload_video(access_token, advertiser_id, image_urls)
    return {
        "image_ids": image_ids,
        "video_id": video_result.get("video_id", ""),
        "video_steps": video_result.get("steps", []),
        "urls_tried": len(image_urls),
    }


# ── Performance Endpoints ──

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