"""TikTok Ads router - OAuth, campaign creation, and performance tracking

v1.2.0 - Add: /pause-all-campaigns, /launch-targeted-campaign, /targeting-categories, /targeting-keywords
v1.1.0 - Fix: /performance endpoint returns per-campaign metrics (spend, impressions, clicks, ctr, cpc)
v1.0.2 - Fix: Add timestamp to campaign name to prevent "name already exists" error
v1.0.1 - Fix: Use video_cover_url from upload response for thumbnail
         Multipart image file upload returns empty image_id.
         URL-based upload from video_cover_url works reliably.

Ad creation strategy priority:
1. SINGLE_VIDEO + TT_USER + video_cover_url thumbnail (9:16 match)
2. SINGLE_VIDEO + TT_USER + poster_url thumbnail (fallback)
3. SINGLE_VIDEO + TT_USER + product image thumbnail
4. Pangle display ad (audience network)

Key insight: TikTok video upload response includes video_cover_url - a 9:16
auto-generated cover image. Uploading this URL as an image via UPLOAD_BY_URL
gives us a thumbnail that perfectly matches the video aspect ratio.
"""

import os
import io
import json
import logging
import time
import hashlib
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

def _safe_get_data(result: dict, *keys):
    """Safely extract nested data from TikTok API responses."""
    raw_data = result.get("data") if isinstance(result, dict) else None
    if isinstance(raw_data, list):
        data = raw_data[0] if raw_data else {}
    elif isinstance(raw_data, dict):
        data = raw_data
    else:
        data = {}
    if not keys:
        return data
    current = data
    for i, key in enumerate(keys):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and current:
            if isinstance(current[0], dict):
                current = current[0].get(key)
            else:
                return [] if key.endswith("s") else ""
        else:
            return [] if key.endswith("s") else ""
        if current is None:
            return [] if key.endswith("s") else ""
    return current


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
    """Upload a file to TikTok using multipart form data with MD5 signature."""
    url = f"{TIKTOK_API_BASE}{endpoint}"
    headers = {"Access-Token": access_token}
    data = {"advertiser_id": advertiser_id}
    if extra_data:
        data.update(extra_data)
    try:
        with open(file_path, "rb") as f:
            file_content = f.read()
        md5_hash = hashlib.md5(file_content).hexdigest()
        data["video_signature"] = md5_hash
        logger.info(f"Upload: file={os.path.basename(file_path)}, size={len(file_content)}, md5={md5_hash}")
        mime = "video/mp4" if file_path.endswith(".mp4") else "image/jpeg"
        files = {file_field: (os.path.basename(file_path), io.BytesIO(file_content), mime)}
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Upload response: code={result.get('code')}, message={result.get('message')}")
        return result
    except Exception as e:
        logger.error(f"TikTok upload error: {e}")
        return {"code": -1, "message": str(e)}


# ── Identity Management ──

def _find_best_identity(access_token: str, advertiser_id: str) -> dict:
    """Find best identity. Priority: TT_USER > BC_AUTH_TT > CUSTOMIZED_USER (deprecated)"""
    for identity_type in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", access_token,
                             params={"advertiser_id": advertiser_id, "identity_type": identity_type})
        if result.get("code") == 0:
            data = _safe_get_data(result)
            identities = data.get("identity_list", [])
            if identities:
                ident = identities[0]
                if identity_type == "CUSTOMIZED_USER":
                    logger.warning("Using CUSTOMIZED_USER identity - deprecated by TikTok, may fail")
                else:
                    logger.info(f"Using {identity_type} identity: {ident.get('identity_id')} ({ident.get('display_name')})")
                return {"identity_id": ident.get("identity_id"),
                        "identity_type": identity_type,
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
            img_id = _safe_get_data(result, "image_id")
            if img_id:
                image_ids.append(img_id)
        elif result.get("code") == 40911:
            result2 = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
                "advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_URL", "image_url": url,
                "file_name": f"cs_u{int(time.time())}_{len(image_ids)}.jpg",
            })
            if result2.get("code") == 0:
                img_id = _safe_get_data(result2, "image_id")
                if img_id:
                    image_ids.append(img_id)
    return image_ids


def _upload_image_by_url(access_token: str, advertiser_id: str, image_url: str,
                         file_name: str = None) -> str:
    """Upload a single image by URL, return image_id."""
    if not image_url:
        return ""
    if not file_name:
        file_name = f"thumb_{int(time.time())}.jpg"
    result = _tiktok_api("POST", "/file/image/ad/upload/", access_token, data={
        "advertiser_id": advertiser_id,
        "upload_type": "UPLOAD_BY_URL",
        "image_url": image_url,
        "file_name": file_name,
    })
    if result.get("code") == 0:
        img_id = _safe_get_data(result, "image_id")
        if img_id:
            logger.info(f"Image uploaded by URL: {img_id}")
            return img_id
    logger.error(f"URL image upload failed: code={result.get('code')}, msg={result.get('message')}")
    return ""


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
    """Full pipeline: download images -> create video -> upload -> get thumbnail from video_cover_url."""
    if not image_urls:
        image_urls = _get_product_images()[:5]
    steps = []

    image_paths = _download_images_for_video(image_urls)
    steps.append({"step": "download_images", "count": len(image_paths)})
    if not image_paths:
        return {"video_id": "", "thumbnail_image_id": "", "steps": steps, "error": "No images downloaded"}

    video_path = tempfile.mktemp(suffix=".mp4")
    success = _create_minimal_mp4(image_paths, video_path, duration_per_image=3)
    steps.append({"step": "create_video", "success": success,
                  "file_size": os.path.getsize(video_path) if success and os.path.exists(video_path) else 0})

    for p in image_paths:
        try:
            os.remove(p)
        except Exception:
            pass

    if not success:
        return {"video_id": "", "thumbnail_image_id": "", "steps": steps,
                "error": "Video creation failed (ffmpeg not available)"}

    video_id = ""
    video_cover_url = ""
    try:
        result = _tiktok_upload(
            "/file/video/ad/upload/", access_token, advertiser_id,
            video_path, file_field="video_file",
            extra_data={"upload_type": "UPLOAD_BY_FILE",
                       "file_name": f"court_sportswear_{int(time.time())}.mp4"})
        upload_data = _safe_get_data(result)
        upload_video_id = upload_data.get("video_id", "") if isinstance(upload_data, dict) else _safe_get_data(result, "video_id")
        video_cover_url = upload_data.get("video_cover_url", "") if isinstance(upload_data, dict) else ""
        steps.append({"step": "upload_video", "code": result.get("code"),
                      "message": result.get("message"), "video_id": upload_video_id,
                      "video_cover_url": video_cover_url[:100] if video_cover_url else ""})
        if result.get("code") == 0 and upload_video_id:
            video_id = upload_video_id
            logger.info(f"Video uploaded: {video_id}, cover_url: {video_cover_url[:80] if video_cover_url else 'none'}")
    except Exception as e:
        steps.append({"step": "upload_video", "error": str(e)})

    try:
        os.remove(video_path)
    except Exception:
        pass

    thumbnail_image_id = ""
    if video_cover_url:
        thumbnail_image_id = _upload_image_by_url(
            access_token, advertiser_id, video_cover_url,
            file_name=f"cover_{int(time.time())}.jpg")
        steps.append({"step": "upload_thumbnail", "image_id": thumbnail_image_id,
                      "method": "video_cover_url"})

    if not thumbnail_image_id and video_id:
        time.sleep(2)
        poster_result = _tiktok_api("GET", "/file/video/ad/info/", access_token,
                                     params={"advertiser_id": advertiser_id,
                                             "video_ids": json.dumps([video_id])})
        if poster_result.get("code") == 0:
            poster_data = _safe_get_data(poster_result)
            video_list = poster_data.get("list", [])
            if video_list:
                poster_url = video_list[0].get("poster_url", "") or video_list[0].get("video_cover_url", "")
                if poster_url:
                    thumbnail_image_id = _upload_image_by_url(
                        access_token, advertiser_id, poster_url,
                        file_name=f"poster_{int(time.time())}.jpg")
                    steps.append({"step": "upload_thumbnail_poster", "image_id": thumbnail_image_id,
                                  "method": "poster_url"})

    return {"video_id": video_id, "thumbnail_image_id": thumbnail_image_id, "steps": steps}


# ── Ad Creation ──

def _try_create_ad(access_token: str, advertiser_id: str, adgroup_id: str,
                   image_id: str, identity: dict, video_id: str = "",
                   campaign_id: str = "", thumbnail_image_id: str = "") -> dict:
    """Try multiple ad creation strategies in priority order."""
    identity_id = identity.get("identity_id", "")
    identity_type = identity.get("identity_type", "TT_USER")
    attempts = []
    best_thumb = thumbnail_image_id or image_id

    if video_id and identity_id and best_thumb:
        creative = {
            "ad_name": f"Court Sportswear - Tennis Video {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Performance gear for every court. Shop now!",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "image_ids": [best_thumb],
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        ad_ids = _safe_get_data(result, "ad_ids")
        attempts.append({"strategy": "video_with_cover_thumb", "code": result.get("code"),
                        "message": result.get("message"), "ad_ids": ad_ids,
                        "thumbnail_used": best_thumb,
                        "identity_type_used": identity_type})
        if result.get("code") == 0 and ad_ids:
            return {"success": True, "ad_ids": ad_ids,
                    "strategy": "video_with_cover_thumb", "attempts": attempts}

    if video_id and identity_id and image_id and image_id != best_thumb:
        creative = {
            "ad_name": f"Court Sportswear - Performance Gear {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Shop court-sportswear.com",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "call_to_action": "SHOP_NOW",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "image_ids": [image_id],
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        ad_ids = _safe_get_data(result, "ad_ids")
        attempts.append({"strategy": "video_with_product_thumb", "code": result.get("code"),
                        "message": result.get("message"), "ad_ids": ad_ids})
        if result.get("code") == 0 and ad_ids:
            return {"success": True, "ad_ids": ad_ids,
                    "strategy": "video_with_product_thumb", "attempts": attempts}

    if video_id and identity_id and best_thumb:
        creative = {
            "ad_name": f"Court Sportswear - Shop Now {int(time.time()) % 10000}",
            "ad_text": "Premium tennis & pickleball apparel. Shop court-sportswear.com",
            "landing_page_url": "https://court-sportswear.com/collections/all",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "image_ids": [best_thumb],
            "identity_id": identity_id,
            "identity_type": identity_type,
        }
        result = _tiktok_api("POST", "/ad/create/", access_token, data={
            "advertiser_id": advertiser_id, "adgroup_id": adgroup_id,
            "creatives": [creative], "operation_status": "ENABLE"})
        ad_ids = _safe_get_data(result, "ad_ids")
        attempts.append({"strategy": "video_no_cta", "code": result.get("code"),
                        "message": result.get("message"), "ad_ids": ad_ids})
        if result.get("code") == 0 and ad_ids:
            return {"success": True, "ad_ids": ad_ids,
                    "strategy": "video_no_cta", "attempts": attempts}

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
        pangle_ag_id = _safe_get_data(ag_result, "adgroup_id")
        attempts.append({"strategy": "create_pangle_adgroup", "code": ag_result.get("code"),
                         "message": ag_result.get("message"), "adgroup_id": pangle_ag_id})
        if ag_result.get("code") == 0 and pangle_ag_id:
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
            ad_ids = _safe_get_data(ad_result, "ad_ids")
            attempts.append({"strategy": "pangle_image_ad", "code": ad_result.get("code"),
                             "message": ad_result.get("message"), "ad_ids": ad_ids})
            if ad_result.get("code") == 0 and ad_ids:
                return {"success": True, "ad_ids": ad_ids,
                        "pangle_adgroup_id": pangle_ag_id, "strategy": "pangle_image",
                        "attempts": attempts}

    if not video_id:
        attempts.append({"strategy": "info", "message": "No video_id available."})
    if not best_thumb:
        attempts.append({"strategy": "info", "message": "No thumbnail available."})

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
        data = _safe_get_data(result)
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
                "advertisers": _safe_get_data(result).get("list", [])}
    return {"connected": False, "message": result.get("message")}


# ── Campaign & Ad Creation ──

@router.post("/launch-campaign", summary="Launch TikTok Ad Campaign")
def launch_campaign(daily_budget: float = Query(20.0),
                    campaign_name: str = Query(None),
                    db: Session = Depends(get_db)):
    """Full campaign launch: campaign -> ad group -> upload images -> generate video + thumbnail -> create ad."""
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected."}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []
    adgroup_budget = max(daily_budget, 20.0)

    if not campaign_name:
        ts = datetime.utcnow().strftime("%m%d_%H%M")
        campaign_name = f"Court Sportswear - Tennis {ts}"

    try:
        camp = _tiktok_api("POST", "/campaign/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_name": campaign_name,
            "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE"})
        steps.append({"step": "campaign", "code": camp.get("code"), "message": camp.get("message")})
        if camp.get("code") != 0:
            return {"success": False, "error": camp.get("message"), "steps": steps}
        campaign_id = _safe_get_data(camp, "campaign_id")
        if not campaign_id:
            return {"success": False, "error": "No campaign_id in response", "steps": steps}

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
        adgroup_id = _safe_get_data(ag, "adgroup_id")
        if not adgroup_id:
            return {"success": False, "error": "No adgroup_id in response", "steps": steps, "campaign_id": campaign_id}

        product_urls = _get_product_images()[:5]
        image_ids = _upload_images(access_token, advertiser_id, product_urls)
        steps.append({"step": "upload_images", "count": len(image_ids)})

        video_result = _generate_and_upload_video(access_token, advertiser_id, product_urls)
        video_id = video_result.get("video_id", "")
        thumbnail_image_id = video_result.get("thumbnail_image_id", "")
        steps.append({"step": "video_generation", "video_id": video_id,
                      "thumbnail_image_id": thumbnail_image_id,
                      "details": video_result.get("steps", [])})

        identity = _find_best_identity(access_token, advertiser_id)
        steps.append({"step": "identity", "result": identity})

        image_id = image_ids[0] if image_ids else ""
        ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                    image_id, identity, video_id, campaign_id,
                                    thumbnail_image_id)
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
                                details=f"Campaign: {campaign_id}, AdGroup: {adgroup_id}, Ad: {ad_id}, Video: {video_id}, Thumb: {thumbnail_image_id}, Strategy: {ad_result.get('strategy', 'none')}"))
        db.commit()

        return {"success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id,
                "ad_id": ad_id, "video_id": video_id,
                "thumbnail_image_id": thumbnail_image_id,
                "daily_budget": adgroup_budget,
                "ad_strategy": ad_result.get("strategy"),
                "ad_warning": None if ad_id else "Ad creation failed. Check steps for details.",
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

    image_urls = [image_url] if image_url else _get_product_images()[:5]
    image_ids = _upload_images(access_token, advertiser_id, image_urls)
    steps.append({"step": "images", "count": len(image_ids), "ids": image_ids})

    video_result = _generate_and_upload_video(access_token, advertiser_id, image_urls)
    video_id = video_result.get("video_id", "")
    thumbnail_image_id = video_result.get("thumbnail_image_id", "")
    steps.append({"step": "video", "video_id": video_id,
                  "thumbnail_image_id": thumbnail_image_id,
                  "details": video_result.get("steps", [])})

    identity = _find_best_identity(access_token, advertiser_id)
    steps.append({"step": "identity", "result": identity})
    if not identity.get("identity_id"):
        return {"success": False, "error": "No identity found.", "steps": steps}

    image_id = image_ids[0] if image_ids else ""
    ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                image_id, identity, video_id, campaign_id,
                                thumbnail_image_id)
    steps.append({"step": "create_ad", "result": ad_result})

    if ad_result.get("success"):
        return {"success": True, "ad_ids": ad_result.get("ad_ids", []),
                "strategy": ad_result.get("strategy"),
                "video_id": video_id, "thumbnail_image_id": thumbnail_image_id,
                "steps": steps}
    return {"success": False, "error": "All strategies failed.", "steps": steps}


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
    video_id = _safe_get_data(result, "video_id") if result.get("code") == 0 else ""
    return {"result": result, "video_id": video_id}


# ── Debug & Info Endpoints ──

@router.get("/images", summary="List uploaded images")
def list_images(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/file/image/ad/get/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"], "page_size": 50})
    data = _safe_get_data(result)
    images = data.get("list", [])
    return {"count": len(images), "images": images,
            "raw_code": result.get("code"), "raw_message": result.get("message")}


@router.get("/videos", summary="List uploaded videos")
def list_videos(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    for endpoint in ["/file/video/ad/info/", "/file/video/ad/get/"]:
        result = _tiktok_api("GET", endpoint, creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"], "page_size": 50})
        if result.get("code") == 0:
            data = _safe_get_data(result)
            videos = data.get("list", [])
            return {"count": len(videos), "videos": videos, "endpoint_used": endpoint}
    return {"count": 0, "videos": [], "raw_code": result.get("code"), "raw_message": result.get("message")}


@router.get("/identities", summary="List all TikTok identities")
def list_identities(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    all_ids = {}
    for it in ["TT_USER", "BC_AUTH_TT", "CUSTOMIZED_USER"]:
        result = _tiktok_api("GET", "/identity/get/", creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"], "identity_type": it})
        data = _safe_get_data(result)
        lst = data.get("identity_list", []) if result.get("code") == 0 else []
        all_ids[it] = {"count": len(lst), "list": lst}
    return {"advertiser_id": creds["advertiser_id"], "identities": all_ids}


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


# ── Performance Endpoints ──

@router.get("/performance", summary="Get TikTok Performance Data (with per-campaign metrics)")
def get_tiktok_performance(db: Session = Depends(get_db)):
    """Fetch TikTok campaign list AND per-campaign performance metrics."""
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"error": "TikTok not connected"}
    try:
        result = _tiktok_api("GET", "/campaign/get/", creds["access_token"],
                           params={"advertiser_id": creds["advertiser_id"], "page_size": 100})
        campaigns_raw = []
        if result.get("code") == 0:
            data = _safe_get_data(result)
            campaigns_raw = data.get("list", [])

        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        campaign_metrics = {}

        stats = _tiktok_api("GET", "/report/integrated/get/", creds["access_token"], params={
            "advertiser_id": creds["advertiser_id"], "report_type": "BASIC",
            "dimensions": json.dumps(["campaign_id"]), "data_level": "AUCTION_CAMPAIGN",
            "start_date": start, "end_date": end,
            "metrics": json.dumps(["spend", "impressions", "clicks", "ctr", "cpc", "reach"])})

        if stats.get("code") == 0:
            stats_data = _safe_get_data(stats)
            for row in stats_data.get("list", []):
                dims = row.get("dimensions", {})
                m = row.get("metrics", {})
                cid = str(dims.get("campaign_id", ""))
                if cid:
                    campaign_metrics[cid] = {
                        "spend": round(float(m.get("spend", 0)), 2),
                        "impressions": int(m.get("impressions", 0)),
                        "clicks": int(m.get("clicks", 0)),
                        "ctr": round(float(m.get("ctr", 0)) * 100, 2),
                        "cpc": round(float(m.get("cpc", 0)), 2),
                        "reach": int(m.get("reach", 0)),
                    }

        total_spend = total_imp = total_clicks = total_reach = 0
        campaigns = []
        for c in campaigns_raw:
            cid = str(c.get("campaign_id", ""))
            metrics = campaign_metrics.get(cid, {})
            spend = metrics.get("spend", 0)
            impressions = metrics.get("impressions", 0)
            clicks = metrics.get("clicks", 0)
            ctr = metrics.get("ctr", 0)
            cpc = metrics.get("cpc", 0)
            reach = metrics.get("reach", 0)

            total_spend += spend
            total_imp += impressions
            total_clicks += clicks
            total_reach += reach

            campaigns.append({
                "id": cid,
                "name": c.get("campaign_name", ""),
                "status": c.get("operation_status", ""),
                "objective": c.get("objective_type", ""),
                "budget": c.get("budget", 0),
                "spend": spend, "impressions": impressions,
                "clicks": clicks, "ctr": ctr, "cpc": cpc, "reach": reach,
            })

        campaigns.sort(key=lambda x: x["spend"], reverse=True)
        avg_ctr = round((total_clicks / total_imp * 100) if total_imp else 0, 2)
        avg_cpc = round((total_spend / total_clicks) if total_clicks else 0, 2)

        return {
            "summary": {
                "total_campaigns": len(campaigns),
                "total_spend": round(total_spend, 2),
                "total_impressions": total_imp,
                "total_clicks": total_clicks,
                "total_reach": total_reach,
                "avg_ctr": avg_ctr,
                "avg_cpc": avg_cpc,
            },
            "campaigns": campaigns,
        }
    except Exception as e:
        logger.error(f"TikTok performance error: {e}")
        return {"error": str(e)}


# ── Targeting Discovery ──

@router.get("/targeting-categories", summary="Get TikTok interest categories for targeting")
def get_targeting_categories(db: Session = Depends(get_db)):
    """Query TikTok interest category taxonomy to find tennis/sports IDs."""
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/tool/interest_category/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"], "language": "en"})
    if result.get("code") != 0:
        return {"error": result.get("message"), "raw": result}
    data = _safe_get_data(result)
    categories = data.get("interest_categories", []) or data.get("list", [])
    sports_keywords = ["sport", "tennis", "fitness", "athletic", "outdoor", "racket",
                       "pickleball", "exercise", "apparel", "clothing", "fashion"]
    relevant = []
    for cat in categories:
        name = (cat.get("interest_category_name", "") or cat.get("name", "")).lower()
        if any(kw in name for kw in sports_keywords):
            relevant.append(cat)
    return {"total_categories": len(categories), "sports_relevant": relevant,
            "all_categories": categories[:100]}


@router.get("/targeting-keywords", summary="Search TikTok interest keywords")
def get_targeting_keywords(keyword: str = Query("tennis"), db: Session = Depends(get_db)):
    """Search TikTok keyword targeting for specific terms like tennis, pickleball."""
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    result = _tiktok_api("GET", "/tool/interest_keyword/recommend/", creds["access_token"],
                         params={"advertiser_id": creds["advertiser_id"],
                                 "keyword": keyword, "language": "en", "limit": 50})
    if result.get("code") != 0:
        result = _tiktok_api("GET", "/tool/interest_keyword/get/", creds["access_token"],
                             params={"advertiser_id": creds["advertiser_id"],
                                     "keyword": keyword, "language": "en"})
    return {"keyword": keyword, "result": result}


# ── Campaign Management (API-level) ──

@router.post("/pause-all-campaigns", summary="Pause ALL TikTok campaigns via API")
def pause_all_campaigns(db: Session = Depends(get_db)):
    """Actually pause campaigns on TikTok platform, not just local DB."""
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    result = _tiktok_api("GET", "/campaign/get/", access_token,
                         params={"advertiser_id": advertiser_id, "page_size": 100})
    if result.get("code") != 0:
        return {"error": result.get("message")}
    data = _safe_get_data(result)
    campaigns = data.get("list", [])
    paused, errors, already_paused = [], [], []
    for c in campaigns:
        cid = str(c.get("campaign_id", ""))
        status = c.get("operation_status", "")
        name = c.get("campaign_name", "")
        if status in ["DISABLE", "FROZEN"]:
            already_paused.append({"id": cid, "name": name, "status": status})
            continue
        pr = _tiktok_api("POST", "/campaign/update/status/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_ids": [cid], "operation_status": "DISABLE"})
        if pr.get("code") == 0:
            paused.append({"id": cid, "name": name})
        else:
            errors.append({"id": cid, "name": name, "error": pr.get("message")})
    try:
        db.query(CampaignModel).filter(CampaignModel.platform == "tiktok").update({"status": "PAUSED"})
        db.add(ActivityLogModel(action="TIKTOK_ALL_CAMPAIGNS_PAUSED", entity_type="campaign",
                                entity_id="all", details=f"Paused {len(paused)} campaigns via API"))
        db.commit()
    except Exception:
        pass
    return {"total_campaigns": len(campaigns), "paused": len(paused),
            "already_paused": len(already_paused), "errors": len(errors),
            "paused_list": paused, "already_paused_list": already_paused, "error_list": errors}


@router.post("/launch-targeted-campaign", summary="Launch properly targeted tennis campaign")
def launch_targeted_campaign(daily_budget: float = Query(20.0),
                             campaign_name: str = Query(None),
                             interest_category_ids: str = Query(None),
                             interest_keyword_ids: str = Query(None),
                             db: Session = Depends(get_db)):
    """Launch campaign with proper tennis/sports interest targeting.
    Auto-discovers sports/fitness categories if no IDs provided."""
    creds = _get_active_token(db)
    if not creds["access_token"] or not creds["advertiser_id"]:
        return {"success": False, "error": "TikTok not connected."}
    access_token, advertiser_id = creds["access_token"], creds["advertiser_id"]
    steps = []
    adgroup_budget = max(daily_budget, 20.0)
    if not campaign_name:
        ts = datetime.utcnow().strftime("%m%d_%H%M")
        campaign_name = f"Court Sportswear - Tennis Targeted {ts}"

    targeting_data = {}
    if interest_category_ids:
        targeting_data["interest_category_ids"] = json.loads(interest_category_ids) if isinstance(interest_category_ids, str) else interest_category_ids
        steps.append({"step": "targeting", "method": "provided", "ids": targeting_data["interest_category_ids"]})
    elif interest_keyword_ids:
        targeting_data["interest_keyword_ids"] = json.loads(interest_keyword_ids) if isinstance(interest_keyword_ids, str) else interest_keyword_ids
        steps.append({"step": "targeting", "method": "provided_keywords"})
    else:
        cat_result = _tiktok_api("GET", "/tool/interest_category/", access_token,
                                 params={"advertiser_id": advertiser_id, "language": "en"})
        if cat_result.get("code") == 0:
            cat_data = _safe_get_data(cat_result)
            all_cats = cat_data.get("interest_categories", []) or cat_data.get("list", [])
            target_names = ["sports", "fitness", "outdoor", "athletic", "apparel", "clothing"]
            found_ids, found_names = [], []
            for cat in all_cats:
                name = (cat.get("interest_category_name", "") or cat.get("name", "")).lower()
                cat_id = cat.get("interest_category_id") or cat.get("id")
                if cat_id and any(t in name for t in target_names):
                    found_ids.append(str(cat_id))
                    found_names.append(name)
            if found_ids:
                targeting_data["interest_category_ids"] = found_ids[:10]
                steps.append({"step": "auto_targeting", "found": len(found_ids),
                             "using": found_ids[:10], "names": found_names[:10]})
            else:
                steps.append({"step": "auto_targeting", "warning": "No matching categories", "total": len(all_cats)})
        else:
            steps.append({"step": "auto_targeting", "error": cat_result.get("message")})

    try:
        camp = _tiktok_api("POST", "/campaign/create/", access_token, data={
            "advertiser_id": advertiser_id, "campaign_name": campaign_name,
            "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE",
            "operation_status": "ENABLE"})
        steps.append({"step": "campaign", "code": camp.get("code"), "message": camp.get("message")})
        if camp.get("code") != 0:
            return {"success": False, "error": camp.get("message"), "steps": steps}
        campaign_id = _safe_get_data(camp, "campaign_id")

        schedule = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        adgroup_data = {
            "advertiser_id": advertiser_id, "campaign_id": campaign_id,
            "adgroup_name": f"{campaign_name} - Tennis Enthusiasts 25-54",
            "placement_type": "PLACEMENT_TYPE_AUTOMATIC", "promotion_type": "WEBSITE",
            "budget_mode": "BUDGET_MODE_DAY", "budget": adgroup_budget,
            "schedule_type": "SCHEDULE_FROM_NOW", "schedule_start_time": schedule,
            "billing_event": "CPC", "optimization_goal": "CLICK",
            "bid_type": "BID_TYPE_NO_BID", "pacing": "PACING_MODE_SMOOTH",
            "operation_status": "ENABLE", "location_ids": ["6252001"],
            "gender": "GENDER_UNLIMITED", "age_groups": ["AGE_25_34", "AGE_35_44", "AGE_45_54"],
        }
        if targeting_data.get("interest_category_ids"):
            adgroup_data["interest_category_ids"] = targeting_data["interest_category_ids"]
        if targeting_data.get("interest_keyword_ids"):
            adgroup_data["interest_keyword_ids"] = targeting_data["interest_keyword_ids"]

        ag = _tiktok_api("POST", "/adgroup/create/", access_token, data=adgroup_data)
        steps.append({"step": "adgroup", "code": ag.get("code"), "message": ag.get("message"), "targeting": targeting_data})
        if ag.get("code") != 0:
            return {"success": False, "error": ag.get("message"), "steps": steps, "campaign_id": campaign_id}
        adgroup_id = _safe_get_data(ag, "adgroup_id")

        product_urls = _get_product_images()[:5]
        image_ids = _upload_images(access_token, advertiser_id, product_urls)
        steps.append({"step": "upload_images", "count": len(image_ids)})

        video_result = _generate_and_upload_video(access_token, advertiser_id, product_urls)
        video_id = video_result.get("video_id", "")
        thumbnail_image_id = video_result.get("thumbnail_image_id", "")
        steps.append({"step": "video", "video_id": video_id, "thumbnail_id": thumbnail_image_id})

        identity = _find_best_identity(access_token, advertiser_id)
        steps.append({"step": "identity", "result": identity})

        image_id = image_ids[0] if image_ids else ""
        ad_result = _try_create_ad(access_token, advertiser_id, adgroup_id,
                                    image_id, identity, video_id, campaign_id, thumbnail_image_id)
        steps.append({"step": "create_ad", "result": ad_result})

        ad_id = None
        if ad_result.get("success"):
            ad_ids = ad_result.get("ad_ids", [])
            ad_id = ad_ids[0] if ad_ids else None

        db.add(CampaignModel(platform="tiktok", platform_campaign_id=str(campaign_id),
                             name=campaign_name, status="ACTIVE", campaign_type="TRAFFIC",
                             daily_budget=adgroup_budget))
        db.add(ActivityLogModel(action="TIKTOK_TARGETED_CAMPAIGN_LAUNCHED", entity_type="campaign",
                                entity_id=str(campaign_id), details=f"Targeted with: {targeting_data}"))
        db.commit()

        return {"success": True, "campaign_id": campaign_id, "adgroup_id": adgroup_id,
                "ad_id": ad_id, "video_id": video_id, "targeting": targeting_data,
                "daily_budget": adgroup_budget, "ad_strategy": ad_result.get("strategy"), "steps": steps}
    except Exception as e:
        return {"success": False, "error": str(e), "steps": steps}


@router.get("/advertiser-info", summary="Get advertiser info")
def get_advertiser_info(db: Session = Depends(get_db)):
    creds = _get_active_token(db)
    if not creds["access_token"]:
        return {"error": "Not connected"}
    return _tiktok_api("GET", "/advertiser/info/", creds["access_token"],
                       params={"advertiser_ids": json.dumps([creds["advertiser_id"]])})
