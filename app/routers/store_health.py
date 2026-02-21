"""
Store Health Monitor — checks court-sportswear.com for CRO elements
Phase 13: Homepage speed, collection page, Judge.me, Meta Pixel,
          free shipping bar, Klaviyo, SSL.
"""

import logging
import time
import ssl
import socket
from datetime import datetime, timezone

import requests
from fastapi import APIRouter

logger = logging.getLogger("AutoSEM.StoreHealth")
router = APIRouter()

STORE_URL = "https://court-sportswear.com"
COLLECTION_PATH = "/collections/all-mens-t-shirts"


def _check_page(url: str, timeout: int = 10):
    """Fetch a page, return (response_time_ms, status_code, body_lower, error)."""
    try:
        start = time.time()
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        elapsed_ms = round((time.time() - start) * 1000)
        return elapsed_ms, resp.status_code, resp.text.lower(), None
    except Exception as e:
        return None, None, "", str(e)


def _check_ssl(hostname: str) -> dict:
    """Check if SSL certificate is valid."""
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(5)
            s.connect((hostname, 443))
            cert = s.getpeercert()
            not_after = cert.get("notAfter", "")
            return {"pass": True, "detail": f"Valid until {not_after}"}
    except Exception as e:
        return {"pass": False, "detail": str(e)}


@router.get("/check", summary="Run store health checks",
            description="Check court-sportswear.com for CRO elements, speed, tracking pixels, and SSL")
def store_health_check():
    checks = []
    passed = 0

    # 1. Homepage response time < 3s
    elapsed_ms, status_code, body, error = _check_page(STORE_URL)
    if error:
        checks.append({"name": "homepage_speed", "pass": False, "detail": f"Error: {error}"})
    elif elapsed_ms and elapsed_ms < 3000:
        checks.append({"name": "homepage_speed", "pass": True, "detail": f"{elapsed_ms}ms (< 3000ms)"})
        passed += 1
    else:
        checks.append({"name": "homepage_speed", "pass": False, "detail": f"{elapsed_ms}ms (>= 3000ms)"})

    # 2. Collection page returns 200
    col_elapsed, col_status, col_body, col_error = _check_page(f"{STORE_URL}{COLLECTION_PATH}")
    if col_error:
        checks.append({"name": "collection_page", "pass": False, "detail": f"Error: {col_error}"})
    elif col_status == 200:
        checks.append({"name": "collection_page", "pass": True, "detail": f"HTTP {col_status}, {col_elapsed}ms"})
        passed += 1
    else:
        checks.append({"name": "collection_page", "pass": False, "detail": f"HTTP {col_status}"})

    # Use homepage body for remaining checks (or collection body as fallback)
    page_body = body or col_body

    # 3. Judge.me reviews installed
    has_judgeme = "judge" in page_body or "jdgm" in page_body
    checks.append({"name": "judgeme_reviews", "pass": has_judgeme,
                    "detail": "Found" if has_judgeme else "Not found in page source"})
    if has_judgeme:
        passed += 1

    # 4. Meta Pixel present
    has_fbq = "fbq" in page_body
    checks.append({"name": "meta_pixel", "pass": has_fbq,
                    "detail": "Found fbq()" if has_fbq else "Not found in page source"})
    if has_fbq:
        passed += 1

    # 5. Free shipping announcement
    has_free_shipping = "free shipping" in page_body
    checks.append({"name": "free_shipping_bar", "pass": has_free_shipping,
                    "detail": "Found" if has_free_shipping else "Not found in page source"})
    if has_free_shipping:
        passed += 1

    # 6. Klaviyo email capture
    has_klaviyo = "klaviyo" in page_body
    checks.append({"name": "klaviyo_tracking", "pass": has_klaviyo,
                    "detail": "Found" if has_klaviyo else "Not found in page source"})
    if has_klaviyo:
        passed += 1

    # 7. SSL certificate valid
    ssl_result = _check_ssl("court-sportswear.com")
    checks.append({"name": "ssl_certificate", **ssl_result})
    if ssl_result["pass"]:
        passed += 1

    total = len(checks)
    overall = "ok" if passed >= total - 1 else ("degraded" if passed >= total // 2 else "critical")

    return {
        "status": overall,
        "score": f"{passed}/{total}",
        "passed": passed,
        "total": total,
        "store_url": STORE_URL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
