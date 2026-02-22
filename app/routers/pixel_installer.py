"""Meta Pixel Auto-Installer for Shopify

CRITICAL: court-sportswear.com has NO Meta Pixel installed.
This means Meta cannot track ANY conversions (PageView, AddToCart, Purchase).
With 509 ad clicks and 0 conversions, this is the #1 revenue blocker.

Endpoints:
  GET  /status  - Check if pixel is installed on the store
  POST /install - Auto-install pixel via Shopify Theme Asset API
  GET  /verify  - Verify pixel fires after installation
"""

import os
import re
import logging
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, MetaTokenModel, ActivityLogModel

logger = logging.getLogger("AutoSEM.PixelInstaller")
router = APIRouter()

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")
STORE_URL = "https://court-sportswear.com"


def _get_meta_token(db: Session) -> str:
    token_record = db.query(MetaTokenModel).first()
    if token_record and token_record.access_token:
        return token_record.access_token
    return os.environ.get("META_ACCESS_TOKEN", "")


def _appsecret_proof(token: str) -> str:
    import hashlib, hmac
    if not META_APP_SECRET:
        return ""
    return hmac.new(META_APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def _shopify_token() -> str:
    """Get Shopify token from the shopify router's cache."""
    try:
        from app.routers.shopify import _get_token
        return _get_token()
    except Exception:
        return os.environ.get("SHOPIFY_ACCESS_TOKEN", "")


def _shopify_api(method: str, endpoint: str, **kwargs) -> dict:
    token = _shopify_token()
    if not token:
        raise HTTPException(status_code=503, detail="No Shopify token available")
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    return resp.json()


def _log_activity(db: Session, action: str, entity_id: str = "", details: str = ""):
    try:
        log = ActivityLogModel(action=action, entity_type="pixel", entity_id=entity_id, details=details)
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ----------------------------------------------------------------
# GET /status - Check pixel installation status
# ----------------------------------------------------------------

@router.get("/status", summary="Check Meta Pixel installation status")
def pixel_status(db: Session = Depends(get_db)):
    """Check if Meta Pixel is installed on court-sportswear.com.
    
    Checks both the live storefront HTML AND the Shopify theme source.
    Also fetches the Meta Pixel ID from the ad account.
    """
    result = {
        "pixel_on_storefront": False,
        "pixel_in_theme": False,
        "pixel_id": None,
        "theme_id": None,
        "theme_name": None,
        "fbq_found": False,
        "fbevents_script_found": False,
        "noscript_found": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Check live storefront
    try:
        resp = requests.get(STORE_URL, timeout=10)
        body = resp.text.lower()
        result["fbq_found"] = "fbq(" in body
        result["fbevents_script_found"] = "connect.facebook.net" in body
        result["noscript_found"] = "facebook.com/tr" in body or "meta.com/tr" in body
        result["pixel_on_storefront"] = result["fbq_found"] and result["fbevents_script_found"]

        # Try to extract pixel ID from fbq('init', 'XXXXXXXX')
        init_match = re.search(r"fbq\(['\"]init['\"],\s*['\"]([0-9]+)['\"]", resp.text)
        if init_match:
            result["pixel_id"] = init_match.group(1)
    except Exception as e:
        result["storefront_error"] = str(e)

    # 2. Get Meta Pixel ID from ad account
    meta_token = _get_meta_token(db)
    if meta_token and META_AD_ACCOUNT_ID:
        try:
            px_resp = requests.get(
                f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
                params={
                    "fields": "id,name,is_unavailable,creation_time",
                    "access_token": meta_token,
                    "appsecret_proof": _appsecret_proof(meta_token),
                },
                timeout=10,
            )
            pixels = px_resp.json().get("data", [])
            if pixels:
                result["meta_pixel_id"] = pixels[0].get("id")
                result["meta_pixel_name"] = pixels[0].get("name")
                result["meta_pixels_count"] = len(pixels)
        except Exception as e:
            result["meta_api_error"] = str(e)

    # 3. Check Shopify theme
    try:
        themes = _shopify_api("GET", "themes.json")
        main_theme = None
        for t in themes.get("themes", []):
            if t.get("role") == "main":
                main_theme = t
                break
        if main_theme:
            result["theme_id"] = main_theme["id"]
            result["theme_name"] = main_theme.get("name", "")

            asset = _shopify_api("GET", f"themes/{main_theme['id']}/assets.json",
                                 params={"asset[key]": "layout/theme.liquid"})
            theme_content = asset.get("asset", {}).get("value", "")
            result["pixel_in_theme"] = "fbq(" in theme_content.lower()
            result["theme_liquid_length"] = len(theme_content)
    except Exception as e:
        result["theme_error"] = str(e)

    # Overall status
    if result["pixel_on_storefront"]:
        result["status"] = "installed"
        result["message"] = "Meta Pixel is active on the storefront"
    elif result["pixel_in_theme"]:
        result["status"] = "in_theme_only"
        result["message"] = "Pixel code found in theme but not rendering on storefront"
    else:
        result["status"] = "missing"
        result["message"] = "CRITICAL: Meta Pixel is NOT installed. 0% conversion tracking."

    return result


# ----------------------------------------------------------------
# POST /install - Auto-install Meta Pixel on Shopify theme
# ----------------------------------------------------------------

PIXEL_SNIPPET_TEMPLATE = """<!-- Meta Pixel Code - Installed by AutoSEM -->
<script>
!function(f,b,e,v,n,t,s)
{{f.fbq||(n=f.fbq=function(){{n.callMethod?
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

ECOMMERCE_EVENTS_TEMPLATE = """<!-- Meta Pixel E-commerce Events - Installed by AutoSEM -->
<script>
(function() {{
  // ViewContent on product pages
  if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {{
    var product = window.ShopifyAnalytics.meta.product;
    fbq('track', 'ViewContent', {{
      content_ids: [product.id.toString()],
      content_name: product.type === 'product' ? document.title : '',
      content_type: 'product',
      value: product.variants ? product.variants[0].price / 100 : 0,
      currency: 'USD'
    }});
  }}

  // AddToCart on form submission
  document.addEventListener('submit', function(e) {{
    var form = e.target;
    if (form && form.action && form.action.indexOf('/cart/add') !== -1) {{
      fbq('track', 'AddToCart', {{
        content_type: 'product',
        currency: 'USD'
      }});
    }}
  }});

  // InitiateCheckout
  document.addEventListener('click', function(e) {{
    var el = e.target;
    while (el && el !== document) {{
      if (el.href && (el.href.indexOf('/checkout') !== -1 || el.name === 'checkout')) {{
        fbq('track', 'InitiateCheckout');
        break;
      }}
      el = el.parentNode;
    }}
  }});
}})();
</script>
<!-- End Meta Pixel E-commerce Events -->"""


@router.post("/install", summary="Auto-install Meta Pixel on Shopify theme")
def install_pixel(db: Session = Depends(get_db)):
    """Install Meta Pixel on the Shopify store's theme.liquid.
    
    1. Fetches Meta Pixel ID from the ad account (or creates one)
    2. Gets the main Shopify theme
    3. Injects pixel base code before </head>
    4. Injects e-commerce event tracking before </body>
    5. PUTs the modified theme.liquid back
    """
    meta_token = _get_meta_token(db)
    if not meta_token:
        return {"status": "error", "message": "No Meta token available. Connect Meta first."}

    # Step 1: Get or create Meta Pixel
    pixel_id = None
    try:
        px_resp = requests.get(
            f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
            params={
                "fields": "id,name",
                "access_token": meta_token,
                "appsecret_proof": _appsecret_proof(meta_token),
            },
            timeout=10,
        )
        pixels = px_resp.json().get("data", [])
        if pixels:
            pixel_id = pixels[0]["id"]
            logger.info(f"Found existing Meta Pixel: {pixel_id}")
        else:
            # Create a new pixel
            create_resp = requests.post(
                f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
                data={
                    "name": "Court Sportswear - AutoSEM",
                    "access_token": meta_token,
                    "appsecret_proof": _appsecret_proof(meta_token),
                },
                timeout=10,
            )
            pixel_id = create_resp.json().get("id")
            logger.info(f"Created new Meta Pixel: {pixel_id}")
    except Exception as e:
        return {"status": "error", "message": f"Failed to get/create Meta Pixel: {e}"}

    if not pixel_id:
        return {"status": "error", "message": "Could not determine Meta Pixel ID"}

    # Step 2: Get main Shopify theme
    try:
        themes = _shopify_api("GET", "themes.json")
        main_theme = None
        for t in themes.get("themes", []):
            if t.get("role") == "main":
                main_theme = t
                break
        if not main_theme:
            return {"status": "error", "message": "No main theme found on Shopify store"}

        theme_id = main_theme["id"]
        theme_name = main_theme.get("name", "")
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch Shopify themes: {e}"}

    # Step 3: Get current theme.liquid
    try:
        asset = _shopify_api("GET", f"themes/{theme_id}/assets.json",
                             params={"asset[key]": "layout/theme.liquid"})
        theme_liquid = asset.get("asset", {}).get("value", "")
        if not theme_liquid:
            return {"status": "error", "message": "theme.liquid is empty or inaccessible"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read theme.liquid: {e}"}

    # Check if already installed
    if "fbq(" in theme_liquid.lower() and pixel_id in theme_liquid:
        return {
            "status": "already_installed",
            "pixel_id": pixel_id,
            "theme_id": theme_id,
            "message": f"Meta Pixel {pixel_id} is already in theme.liquid",
        }

    # Step 4: Inject pixel code
    pixel_code = PIXEL_SNIPPET_TEMPLATE.format(pixel_id=pixel_id)
    ecommerce_code = ECOMMERCE_EVENTS_TEMPLATE

    # Remove any existing AutoSEM pixel code (in case of partial install)
    theme_liquid = re.sub(
        r'<!-- Meta Pixel Code - Installed by AutoSEM -->.*?<!-- End Meta Pixel Code -->',
        '', theme_liquid, flags=re.DOTALL
    )
    theme_liquid = re.sub(
        r'<!-- Meta Pixel E-commerce Events - Installed by AutoSEM -->.*?<!-- End Meta Pixel E-commerce Events -->',
        '', theme_liquid, flags=re.DOTALL
    )

    # Inject before </head>
    if '</head>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</head>', pixel_code + '\n</head>', 1)
    elif '</HEAD>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</HEAD>', pixel_code + '\n</HEAD>', 1)
    else:
        # Fallback: prepend to file
        theme_liquid = pixel_code + '\n' + theme_liquid

    # Inject e-commerce events before </body>
    if '</body>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</body>', ecommerce_code + '\n</body>', 1)
    elif '</BODY>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</BODY>', ecommerce_code + '\n</BODY>', 1)

    # Step 5: PUT modified theme.liquid back
    try:
        put_result = _shopify_api(
            "PUT", f"themes/{theme_id}/assets.json",
            json={"asset": {"key": "layout/theme.liquid", "value": theme_liquid}}
        )
        if put_result.get("asset"):
            _log_activity(db, "PIXEL_INSTALLED", pixel_id,
                         f"Meta Pixel {pixel_id} installed on theme '{theme_name}' (ID: {theme_id})")
            logger.info(f"Meta Pixel {pixel_id} successfully installed on Shopify theme {theme_id}")
            return {
                "status": "installed",
                "pixel_id": pixel_id,
                "theme_id": theme_id,
                "theme_name": theme_name,
                "events_added": ["PageView", "ViewContent", "AddToCart", "InitiateCheckout"],
                "message": f"Meta Pixel {pixel_id} installed! Conversion tracking is now active.",
                "next_steps": [
                    "Visit court-sportswear.com and verify pixel fires (check /api/v1/pixel/verify)",
                    "Wait 1-2 hours for Meta to receive events",
                    "Meta will begin optimizing ad delivery based on conversion data",
                ],
            }
        else:
            error = put_result.get("errors", put_result)
            return {"status": "error", "message": f"Shopify rejected the theme update: {error}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to update theme.liquid: {e}"}


# ----------------------------------------------------------------
# GET /verify - Verify pixel installation
# ----------------------------------------------------------------

@router.get("/verify", summary="Verify Meta Pixel is firing")
def verify_pixel(db: Session = Depends(get_db)):
    """After installation, verify the pixel is rendering on the live site."""
    result = {
        "storefront_check": {},
        "meta_events_check": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Check live storefront
    try:
        resp = requests.get(STORE_URL, timeout=10)
        body = resp.text
        body_lower = body.lower()

        has_fbq = "fbq(" in body_lower
        has_script = "connect.facebook.net" in body_lower
        has_noscript = "facebook.com/tr" in body_lower or "meta.com/tr" in body_lower

        init_match = re.search(r"fbq\(['\"]init['\"],\s*['\"]([0-9]+)['\"]", body)
        pixel_id = init_match.group(1) if init_match else None

        has_ecommerce = "ViewContent" in body and "AddToCart" in body

        result["storefront_check"] = {
            "fbq_function": has_fbq,
            "fbevents_script": has_script,
            "noscript_fallback": has_noscript,
            "pixel_id_found": pixel_id,
            "ecommerce_events": has_ecommerce,
            "all_checks_pass": all([has_fbq, has_script, has_noscript]),
        }
    except Exception as e:
        result["storefront_check"] = {"error": str(e)}

    # Check Meta for recent events
    meta_token = _get_meta_token(db)
    pixel_id_for_stats = result["storefront_check"].get("pixel_id_found")
    if meta_token and pixel_id_for_stats:
        try:
            stats_resp = requests.get(
                f"{META_GRAPH_BASE}/{pixel_id_for_stats}/stats",
                params={
                    "access_token": meta_token,
                    "appsecret_proof": _appsecret_proof(meta_token),
                },
                timeout=10,
            )
            stats = stats_resp.json()
            result["meta_events_check"] = {
                "stats": stats.get("data", stats),
                "note": "Events may take 1-2 hours to appear after pixel installation",
            }
        except Exception as e:
            result["meta_events_check"] = {"error": str(e)}

    # Overall verdict
    checks = result["storefront_check"]
    if checks.get("all_checks_pass"):
        result["verdict"] = "PASS"
        result["message"] = "Meta Pixel is installed and rendering correctly!"
    elif checks.get("fbq_function"):
        result["verdict"] = "PARTIAL"
        result["message"] = "Pixel base code found but some elements missing"
    else:
        result["verdict"] = "FAIL"
        result["message"] = "Meta Pixel is NOT rendering on the storefront"

    return result
