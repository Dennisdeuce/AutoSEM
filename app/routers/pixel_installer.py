"""
Meta Pixel Auto-Installer Router
Checks, installs, and verifies Meta Pixel on Shopify theme.

CRITICAL: Without Meta Pixel, Meta cannot track conversions after ad clicks.
This is the #1 reason for 509 clicks / 0 conversions.
"""

import os
import re
import logging
import time

import requests
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db, MetaTokenModel, ActivityLogModel

logger = logging.getLogger("AutoSEM.Pixel")
router = APIRouter()

# ─── Shopify Config (mirrors shopify.py) ─────────────────────────
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")

# ─── Meta Config (mirrors meta.py) ──────────────────────────────
META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_GRAPH_BASE = "https://graph.facebook.com/v19.0"


# ─── Shopify Helpers (reuse token logic from shopify router) ─────

def _get_shopify_token() -> str:
    """Get valid Shopify token via the shopify router's token cache."""
    try:
        from app.routers.shopify import _get_token
        return _get_token()
    except Exception as e:
        logger.error(f"Failed to get Shopify token: {e}")
        return ""


def _shopify_api(method: str, endpoint: str, **kwargs) -> dict:
    """Make authenticated Shopify Admin API request."""
    token = _get_shopify_token()
    if not token:
        return {"error": "No Shopify token available"}

    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)

    if resp.status_code == 401:
        # Force refresh and retry
        try:
            from app.routers.shopify import _token_cache
            _token_cache["expires_at"] = 0
        except Exception:
            pass
        token = _get_shopify_token()
        headers["X-Shopify-Access-Token"] = token
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)

    return resp.json()


# ─── Meta Helpers (reuse token logic from meta router) ───────────

def _get_meta_token(db: Session) -> str:
    """Get active Meta access token from DB or env."""
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


def _meta_api(method: str, path: str, token: str, **kwargs) -> dict:
    """Make authenticated Meta Graph API request."""
    params = kwargs.pop("params", {})
    params["access_token"] = token
    proof = _appsecret_proof(token)
    if proof:
        params["appsecret_proof"] = proof
    resp = requests.request(
        method, f"{META_GRAPH_BASE}/{path}",
        params=params, timeout=20, **kwargs,
    )
    return resp.json()


def _log_activity(db: Session, action: str, entity_id: str = "", details: str = ""):
    try:
        log = ActivityLogModel(
            action=action,
            entity_type="pixel",
            entity_id=entity_id,
            details=details,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ─── Meta Pixel Code Templates ──────────────────────────────────

def _pixel_base_code(pixel_id: str) -> str:
    """Standard Meta Pixel base code snippet for <head>."""
    return f"""<!-- Meta Pixel Code (installed by AutoSEM) -->
<script>
!function(f,b,e,v,n,t,s)
{{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{pixel_id}');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id={pixel_id}&ev=PageView&noscript=1"
/></noscript>
<!-- End Meta Pixel Code -->"""


def _pixel_event_code(pixel_id: str) -> str:
    """Shopify-specific event tracking snippets for before </body>."""
    return f"""<!-- Meta Pixel Events (installed by AutoSEM) -->
<script>
(function() {{
  // ViewContent on product pages
  {{% if template contains 'product' %}}
  fbq('track', 'ViewContent', {{
    content_name: '{{{{ product.title | escape }}}}',
    content_ids: ['{{{{ product.id }}}}'],
    content_type: 'product',
    value: {{{{ product.price | money_without_currency | remove: ',' }}}},
    currency: '{{{{ shop.currency }}}}'
  }});
  {{% endif %}}

  // AddToCart on form submit
  document.querySelectorAll('form[action*="/cart/add"]').forEach(function(form) {{
    form.addEventListener('submit', function() {{
      {{% if product %}}
      fbq('track', 'AddToCart', {{
        content_name: '{{{{ product.title | escape }}}}',
        content_ids: ['{{{{ product.id }}}}'],
        content_type: 'product',
        value: {{{{ product.price | money_without_currency | remove: ',' }}}},
        currency: '{{{{ shop.currency }}}}'
      }});
      {{% else %}}
      fbq('track', 'AddToCart');
      {{% endif %}}
    }});
  }});

  // InitiateCheckout
  document.querySelectorAll('a[href*="/checkout"], button[name="checkout"]').forEach(function(el) {{
    el.addEventListener('click', function() {{
      fbq('track', 'InitiateCheckout');
    }});
  }});
}})();
</script>
<!-- End Meta Pixel Events -->"""


# ─── Endpoints ───────────────────────────────────────────────────

@router.get("/status", summary="Check Meta Pixel installation status",
            description="Scan Shopify theme.liquid for fbq() and fetch pixel ID from Meta")
def pixel_status(db: Session = Depends(get_db)):
    """Check if Meta Pixel is installed on the Shopify store theme."""
    result = {
        "pixel_on_store": False,
        "pixel_id": None,
        "theme_id": None,
        "theme_name": None,
        "has_fbq_init": False,
        "has_fbevents_js": False,
        "has_pageview": False,
        "has_viewcontent": False,
        "has_addtocart": False,
        "meta_pixel_ids": [],
    }

    # Step 1: Get main theme from Shopify
    try:
        themes_data = _shopify_api("GET", "themes.json")
        themes = themes_data.get("themes", [])
        main_theme = None
        for t in themes:
            if t.get("role") == "main":
                main_theme = t
                break

        if not main_theme:
            return {**result, "error": "No main theme found"}

        result["theme_id"] = main_theme["id"]
        result["theme_name"] = main_theme.get("name", "")
    except Exception as e:
        return {**result, "error": f"Failed to fetch themes: {e}"}

    # Step 2: Fetch theme.liquid content
    try:
        asset_data = _shopify_api(
            "GET",
            f"themes/{main_theme['id']}/assets.json",
            params={"asset[key]": "layout/theme.liquid"},
        )
        asset = asset_data.get("asset", {})
        theme_liquid = asset.get("value", "")

        if not theme_liquid:
            return {**result, "error": "theme.liquid is empty or inaccessible"}

        result["has_fbq_init"] = "fbq('init'" in theme_liquid or 'fbq("init"' in theme_liquid
        result["has_fbevents_js"] = "connect.facebook.net" in theme_liquid
        result["has_pageview"] = "fbq('track', 'PageView')" in theme_liquid or 'fbq("track", "PageView")' in theme_liquid
        result["has_viewcontent"] = "ViewContent" in theme_liquid
        result["has_addtocart"] = "AddToCart" in theme_liquid
        result["pixel_on_store"] = result["has_fbq_init"] and result["has_fbevents_js"]

        # Extract pixel ID(s) from theme.liquid
        pixel_ids_in_theme = re.findall(r"fbq\(['\"]init['\"],\s*['\"](\d+)['\"]", theme_liquid)
        if pixel_ids_in_theme:
            result["pixel_id"] = pixel_ids_in_theme[0]
            result["pixel_ids_in_theme"] = pixel_ids_in_theme

    except Exception as e:
        result["theme_liquid_error"] = str(e)

    # Step 3: Get pixel ID from Meta Graph API
    meta_token = _get_meta_token(db)
    if meta_token and META_AD_ACCOUNT_ID:
        try:
            pixels_data = _meta_api(
                "GET", f"act_{META_AD_ACCOUNT_ID}/adspixels",
                meta_token,
                params={"fields": "id,name,last_fired_time,is_created_by_business"},
            )
            pixels = pixels_data.get("data", [])
            result["meta_pixel_ids"] = [
                {"id": p.get("id"), "name": p.get("name"), "last_fired": p.get("last_fired_time")}
                for p in pixels
            ]
            if pixels and not result["pixel_id"]:
                result["pixel_id"] = pixels[0]["id"]
        except Exception as e:
            result["meta_api_error"] = str(e)

    return result


@router.post("/install", summary="Auto-install Meta Pixel on Shopify theme",
             description="Fetches pixel ID from Meta, injects base code + events into theme.liquid")
def install_pixel(db: Session = Depends(get_db)):
    """Install Meta Pixel base code and event tracking into the Shopify theme."""
    meta_token = _get_meta_token(db)
    if not meta_token:
        return {"status": "error", "message": "No Meta token available"}
    if not META_AD_ACCOUNT_ID:
        return {"status": "error", "message": "META_AD_ACCOUNT_ID not set"}

    # Step 1: Get or create Meta Pixel
    pixel_id = None
    try:
        pixels_data = _meta_api(
            "GET", f"act_{META_AD_ACCOUNT_ID}/adspixels",
            meta_token,
            params={"fields": "id,name"},
        )
        pixels = pixels_data.get("data", [])
        if pixels:
            pixel_id = pixels[0]["id"]
            logger.info(f"Found existing Meta Pixel: {pixel_id}")
        else:
            # Create a new pixel
            create_resp = _meta_api(
                "POST", f"act_{META_AD_ACCOUNT_ID}/adspixels",
                meta_token,
                data={"name": "Court Sportswear"},
            )
            pixel_id = create_resp.get("id")
            if not pixel_id:
                return {"status": "error", "message": "Failed to create Meta Pixel", "response": create_resp}
            logger.info(f"Created new Meta Pixel: {pixel_id}")
    except Exception as e:
        return {"status": "error", "message": f"Meta Pixel API error: {e}"}

    # Step 2: Get main theme
    try:
        themes_data = _shopify_api("GET", "themes.json")
        themes = themes_data.get("themes", [])
        main_theme = None
        for t in themes:
            if t.get("role") == "main":
                main_theme = t
                break
        if not main_theme:
            return {"status": "error", "message": "No main Shopify theme found"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch themes: {e}"}

    theme_id = main_theme["id"]

    # Step 3: Fetch current theme.liquid
    try:
        asset_data = _shopify_api(
            "GET",
            f"themes/{theme_id}/assets.json",
            params={"asset[key]": "layout/theme.liquid"},
        )
        asset = asset_data.get("asset", {})
        theme_liquid = asset.get("value", "")
        if not theme_liquid:
            return {"status": "error", "message": "theme.liquid is empty or inaccessible"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch theme.liquid: {e}"}

    # Step 4: Check if pixel is already installed
    already_installed = "fbq('init'" in theme_liquid or 'fbq("init"' in theme_liquid
    if already_installed:
        existing_ids = re.findall(r"fbq\(['\"]init['\"],\s*['\"](\d+)['\"]", theme_liquid)
        if pixel_id in existing_ids:
            return {
                "status": "already_installed",
                "pixel_id": pixel_id,
                "theme_id": theme_id,
                "message": f"Meta Pixel {pixel_id} is already in theme.liquid",
            }

    # Step 5: Inject pixel base code before </head>
    base_code = _pixel_base_code(pixel_id)
    event_code = _pixel_event_code(pixel_id)

    modified = theme_liquid
    head_injected = False
    body_injected = False

    # Inject base code before </head>
    if "</head>" in modified:
        modified = modified.replace("</head>", f"{base_code}\n</head>", 1)
        head_injected = True
    elif "</HEAD>" in modified:
        modified = modified.replace("</HEAD>", f"{base_code}\n</HEAD>", 1)
        head_injected = True

    # Inject event code before </body>
    if "</body>" in modified:
        modified = modified.replace("</body>", f"{event_code}\n</body>", 1)
        body_injected = True
    elif "</BODY>" in modified:
        modified = modified.replace("</BODY>", f"{event_code}\n</BODY>", 1)
        body_injected = True

    if not head_injected:
        return {"status": "error", "message": "Could not find </head> in theme.liquid"}

    # Step 6: Write modified theme.liquid back
    try:
        put_data = _shopify_api(
            "PUT",
            f"themes/{theme_id}/assets.json",
            json={
                "asset": {
                    "key": "layout/theme.liquid",
                    "value": modified,
                }
            },
        )
        if put_data.get("asset"):
            events = ["PageView"]
            if body_injected:
                events.extend(["ViewContent", "AddToCart", "InitiateCheckout"])

            _log_activity(
                db, "PIXEL_INSTALLED", pixel_id,
                f"Meta Pixel {pixel_id} installed on theme {main_theme.get('name', '')} "
                f"(theme_id={theme_id}). Events: {', '.join(events)}",
            )

            return {
                "status": "installed",
                "pixel_id": pixel_id,
                "theme_id": theme_id,
                "theme_name": main_theme.get("name", ""),
                "head_injected": head_injected,
                "body_injected": body_injected,
                "events": events,
            }
        else:
            return {"status": "error", "message": "Shopify asset PUT failed", "response": put_data}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write theme.liquid: {e}"}


@router.get("/verify", summary="Verify Meta Pixel fires on live site",
            description="Fetch court-sportswear.com HTML and check for pixel code, then check Meta stats")
def verify_pixel(db: Session = Depends(get_db)):
    """Verify Meta Pixel is present on the live store and check for recent events."""
    report = {
        "site_check": {},
        "meta_stats": {},
        "verdict": "unknown",
    }

    # Step 1: Fetch live site HTML
    try:
        resp = requests.get(
            "https://court-sportswear.com",
            timeout=15,
            headers={"User-Agent": "AutoSEM-PixelVerifier/1.0"},
        )
        html = resp.text

        has_fbq_init = "fbq('init'" in html or 'fbq("init"' in html
        has_fbevents = "connect.facebook.net" in html
        has_pageview = "PageView" in html
        has_noscript = "facebook.com/tr?" in html

        pixel_ids = re.findall(r"fbq\(['\"]init['\"],\s*['\"](\d+)['\"]", html)

        report["site_check"] = {
            "url": "https://court-sportswear.com",
            "status_code": resp.status_code,
            "has_fbq_init": has_fbq_init,
            "has_fbevents_js": has_fbevents,
            "has_pageview": has_pageview,
            "has_noscript_fallback": has_noscript,
            "pixel_ids_found": pixel_ids,
            "html_length": len(html),
        }
    except Exception as e:
        report["site_check"] = {"error": str(e)}

    # Step 2: Check Meta Graph API for pixel stats
    meta_token = _get_meta_token(db)
    if meta_token and META_AD_ACCOUNT_ID:
        try:
            # Get pixel IDs
            pixels_data = _meta_api(
                "GET", f"act_{META_AD_ACCOUNT_ID}/adspixels",
                meta_token,
                params={"fields": "id,name,last_fired_time"},
            )
            pixels = pixels_data.get("data", [])

            pixel_stats = []
            for p in pixels:
                pid = p["id"]
                # Get recent stats
                try:
                    stats_data = _meta_api(
                        "GET", f"{pid}/stats",
                        meta_token,
                        params={"aggregation": "event", "start_time": str(int(time.time()) - 86400)},
                    )
                    pixel_stats.append({
                        "pixel_id": pid,
                        "name": p.get("name", ""),
                        "last_fired": p.get("last_fired_time"),
                        "stats": stats_data.get("data", []),
                    })
                except Exception:
                    pixel_stats.append({
                        "pixel_id": pid,
                        "name": p.get("name", ""),
                        "last_fired": p.get("last_fired_time"),
                        "stats_error": "Could not fetch stats",
                    })

            report["meta_stats"] = {
                "pixels_count": len(pixels),
                "pixels": pixel_stats,
            }
        except Exception as e:
            report["meta_stats"] = {"error": str(e)}

    # Verdict
    site = report.get("site_check", {})
    if site.get("has_fbq_init") and site.get("has_fbevents_js"):
        report["verdict"] = "INSTALLED"
        report["message"] = f"Meta Pixel detected on court-sportswear.com (IDs: {site.get('pixel_ids_found', [])})"
    elif site.get("error"):
        report["verdict"] = "CHECK_FAILED"
        report["message"] = f"Could not fetch site: {site.get('error')}"
    else:
        report["verdict"] = "NOT_INSTALLED"
        report["message"] = "Meta Pixel NOT found on court-sportswear.com — conversions cannot be tracked"

    return report
