#!/usr/bin/env python3
"""Emergency Meta Pixel Installer — Run directly on Replit Shell.

Usage (in Replit Shell):
    python scripts/install_pixel_now.py

This script:
1. Gets a Shopify access token via client_credentials
2. Fetches the Meta Pixel ID from the Meta Graph API
3. Gets the active Shopify theme's theme.liquid
4. Injects Meta Pixel base code before </head>
5. Injects ecommerce event tracking before </body>
6. PUTs the modified theme.liquid back to Shopify
7. Verifies the pixel is live on court-sportswear.com

WHY: court-sportswear.com has NO Meta Pixel. This means Meta can't
track ANY conversions. With 509 ad clicks and 0 purchases, this is
the #1 revenue blocker.
"""

import os
import re
import sys
import time
import hashlib
import hmac
import json

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

# ── Configuration ───────────────────────────────────────
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")

META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
META_GRAPH_BASE = "https://graph.facebook.com/v19.0"

STORE_URL = "https://court-sportswear.com"

# ── Pixel Code Templates ───────────────────────────────
PIXEL_SNIPPET = """<!-- Meta Pixel Code - Installed by AutoSEM -->
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

ECOMMERCE_EVENTS = """<!-- Meta Pixel E-commerce Events - Installed by AutoSEM -->
<script>
(function() {
  // ViewContent on product pages
  if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {
    var product = window.ShopifyAnalytics.meta.product;
    fbq('track', 'ViewContent', {
      content_ids: [product.id.toString()],
      content_name: product.type === 'product' ? document.title : '',
      content_type: 'product',
      value: product.variants ? product.variants[0].price / 100 : 0,
      currency: 'USD'
    });
  }

  // AddToCart on form submission
  document.addEventListener('submit', function(e) {
    var form = e.target;
    if (form && form.action && form.action.indexOf('/cart/add') !== -1) {
      fbq('track', 'AddToCart', {
        content_type: 'product',
        currency: 'USD'
      });
    }
  });

  // InitiateCheckout
  document.addEventListener('click', function(e) {
    var el = e.target;
    while (el && el !== document) {
      if (el.href && (el.href.indexOf('/checkout') !== -1 || el.name === 'checkout')) {
        fbq('track', 'InitiateCheckout');
        break;
      }
      el = el.parentNode;
    }
  });
})();
</script>
<!-- End Meta Pixel E-commerce Events -->"""


def appsecret_proof(token):
    if not META_APP_SECRET:
        return ""
    return hmac.new(META_APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def get_shopify_token():
    """Get Shopify access token via client_credentials."""
    # First check if there's already a token in env
    env_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
    if env_token:
        print(f"  Using existing SHOPIFY_ACCESS_TOKEN from env ({env_token[:12]}...)")
        return env_token

    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("ERROR: SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET must be set")
        sys.exit(1)

    print(f"  Refreshing Shopify token for {SHOPIFY_STORE}...")
    resp = requests.post(
        f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        print(f"ERROR: No access token in response: {data}")
        sys.exit(1)
    print(f"  Got Shopify token: {token[:12]}... (expires in {data.get('expires_in', '?')}s)")
    return token


def shopify_api(token, method, endpoint, **kwargs):
    """Make an authenticated Shopify Admin API request."""
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    return resp.json()


def get_meta_pixel_id():
    """Get the Meta Pixel ID from the ad account."""
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        print("WARNING: META_ACCESS_TOKEN or META_AD_ACCOUNT_ID not set")
        return None

    print(f"  Fetching Meta Pixel ID for ad account {META_AD_ACCOUNT_ID}...")
    resp = requests.get(
        f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
        params={
            "fields": "id,name,is_unavailable,creation_time",
            "access_token": META_ACCESS_TOKEN,
            "appsecret_proof": appsecret_proof(META_ACCESS_TOKEN),
        },
        timeout=10,
    )
    data = resp.json()
    pixels = data.get("data", [])
    if pixels:
        pixel = pixels[0]
        print(f"  Found Meta Pixel: {pixel['id']} ({pixel.get('name', 'unnamed')})")
        return pixel["id"]

    # Create a new pixel if none exists
    print("  No pixel found — creating one...")
    create_resp = requests.post(
        f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/adspixels",
        data={
            "name": "Court Sportswear - AutoSEM",
            "access_token": META_ACCESS_TOKEN,
            "appsecret_proof": appsecret_proof(META_ACCESS_TOKEN),
        },
        timeout=10,
    )
    pixel_id = create_resp.json().get("id")
    if pixel_id:
        print(f"  Created Meta Pixel: {pixel_id}")
    else:
        print(f"  ERROR creating pixel: {create_resp.json()}")
    return pixel_id


def check_current_status():
    """Check if pixel is already on the storefront."""
    print(f"\n  Checking {STORE_URL} for existing pixel...")
    try:
        resp = requests.get(STORE_URL, timeout=10)
        body = resp.text.lower()
        has_fbq = "fbq(" in body
        has_script = "connect.facebook.net" in body
        has_noscript = "facebook.com/tr" in body or "meta.com/tr" in body

        if has_fbq and has_script:
            init_match = re.search(r"fbq\(['\"]init['\"],\s*['\"]([0-9]+)['\"]", resp.text)
            pixel_id = init_match.group(1) if init_match else "unknown"
            print(f"  Pixel ALREADY installed (ID: {pixel_id})")
            return True
        else:
            print(f"  fbq: {'YES' if has_fbq else 'NO'} | "
                  f"fbevents.js: {'YES' if has_script else 'NO'} | "
                  f"noscript: {'YES' if has_noscript else 'NO'}")
            print("  Pixel NOT found — proceeding with installation")
            return False
    except Exception as e:
        print(f"  WARNING: Could not check storefront: {e}")
        return False


def main():
    print("=" * 60)
    print("  META PIXEL INSTALLER — AutoSEM Emergency Script")
    print("=" * 60)

    # Step 0: Check if already installed
    if check_current_status():
        print("\nPixel is already installed! No action needed.")
        return

    # Step 1: Get Meta Pixel ID
    print("\n[1/5] Getting Meta Pixel ID...")
    pixel_id = get_meta_pixel_id()
    if not pixel_id:
        print("FATAL: Could not get Meta Pixel ID. Check META_ACCESS_TOKEN.")
        sys.exit(1)

    # Step 2: Get Shopify token
    print("\n[2/5] Getting Shopify access token...")
    shopify_token = get_shopify_token()

    # Step 3: Get active theme
    print("\n[3/5] Finding active Shopify theme...")
    themes = shopify_api(shopify_token, "GET", "themes.json")
    main_theme = None
    for t in themes.get("themes", []):
        if t.get("role") == "main":
            main_theme = t
            break

    if not main_theme:
        print("FATAL: No main theme found on Shopify store")
        print(f"  Themes: {json.dumps(themes, indent=2)}")
        sys.exit(1)

    theme_id = main_theme["id"]
    theme_name = main_theme.get("name", "")
    print(f"  Active theme: '{theme_name}' (ID: {theme_id})")

    # Step 4: Get theme.liquid and inject pixel
    print("\n[4/5] Reading theme.liquid and injecting pixel code...")
    asset = shopify_api(shopify_token, "GET", f"themes/{theme_id}/assets.json",
                        params={"asset[key]": "layout/theme.liquid"})
    theme_liquid = asset.get("asset", {}).get("value", "")
    if not theme_liquid:
        print(f"FATAL: theme.liquid is empty or inaccessible")
        print(f"  Response: {json.dumps(asset, indent=2)[:500]}")
        sys.exit(1)

    print(f"  theme.liquid: {len(theme_liquid)} chars")

    # Check if already in theme but not rendering
    if "fbq(" in theme_liquid.lower() and pixel_id in theme_liquid:
        print(f"  Pixel {pixel_id} already in theme.liquid (but not rendering on storefront)")
        print("  Skipping injection — investigate theme rendering issue")
        return

    # Remove any existing AutoSEM pixel code (partial install cleanup)
    theme_liquid = re.sub(
        r'<!-- Meta Pixel Code - Installed by AutoSEM -->.*?<!-- End Meta Pixel Code -->',
        '', theme_liquid, flags=re.DOTALL
    )
    theme_liquid = re.sub(
        r'<!-- Meta Pixel E-commerce Events - Installed by AutoSEM -->.*?<!-- End Meta Pixel E-commerce Events -->',
        '', theme_liquid, flags=re.DOTALL
    )

    # Inject pixel base code before </head>
    pixel_code = PIXEL_SNIPPET.format(pixel_id=pixel_id)
    if '</head>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</head>', pixel_code + '\n</head>', 1)
        print("  Injected pixel base code before </head>")
    elif '</HEAD>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</HEAD>', pixel_code + '\n</HEAD>', 1)
        print("  Injected pixel base code before </HEAD>")
    else:
        theme_liquid = pixel_code + '\n' + theme_liquid
        print("  WARNING: No </head> found — prepended pixel code")

    # Inject ecommerce events before </body>
    if '</body>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</body>', ECOMMERCE_EVENTS + '\n</body>', 1)
        print("  Injected ecommerce events before </body>")
    elif '</BODY>' in theme_liquid:
        theme_liquid = theme_liquid.replace('</BODY>', ECOMMERCE_EVENTS + '\n</BODY>', 1)
        print("  Injected ecommerce events before </BODY>")
    else:
        print("  WARNING: No </body> found — ecommerce events not added")

    # Step 5: PUT modified theme.liquid back
    print(f"\n[5/5] Saving modified theme.liquid ({len(theme_liquid)} chars)...")
    put_result = shopify_api(
        shopify_token, "PUT", f"themes/{theme_id}/assets.json",
        json={"asset": {"key": "layout/theme.liquid", "value": theme_liquid}}
    )

    if put_result.get("asset"):
        print("\n" + "=" * 60)
        print("  SUCCESS! Meta Pixel installed!")
        print("=" * 60)
        print(f"  Pixel ID:  {pixel_id}")
        print(f"  Theme:     {theme_name} (ID: {theme_id})")
        print(f"  Events:    PageView, ViewContent, AddToCart, InitiateCheckout")
        print()
        print("  Next steps:")
        print("  1. Visit https://court-sportswear.com — verify pixel fires")
        print("  2. Wait 1-2 hours for Meta to receive events")
        print("  3. Meta will begin optimizing ad delivery for conversions")
        print("  4. Switch campaign objective from LINK_CLICKS to OUTCOME_SALES")
    else:
        errors = put_result.get("errors", put_result)
        print(f"\n  FAILED: Shopify rejected the update")
        print(f"  Error: {json.dumps(errors, indent=2)[:500]}")
        sys.exit(1)

    # Verify
    print(f"\n  Verifying installation on {STORE_URL}...")
    time.sleep(3)
    try:
        resp = requests.get(STORE_URL, timeout=10)
        body = resp.text
        has_fbq = "fbq(" in body.lower()
        has_script = "connect.facebook.net" in body.lower()
        init_match = re.search(r"fbq\(['\"]init['\"],\s*['\"]([0-9]+)['\"]", body)

        if has_fbq and has_script and init_match:
            print(f"  VERIFIED: Pixel {init_match.group(1)} is live on the storefront!")
        elif has_fbq:
            print("  PARTIAL: fbq found but missing fbevents.js script")
        else:
            print("  WARNING: Pixel not yet visible on storefront (may take a few seconds)")
            print("  Try: curl -s https://court-sportswear.com | grep -c 'fbq('")
    except Exception as e:
        print(f"  Could not verify: {e}")


if __name__ == "__main__":
    main()
