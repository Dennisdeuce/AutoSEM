"""
Shopify Integration Router - Token Management & Product Operations
v1.0.0 - Auto-refresh client_credentials tokens, product CRUD

Shopify tokens expire every 24 hours. This router handles:
- Automatic token refresh via client_credentials grant
- Product listing and updates
- Collection management
- Store health checks
"""

import os
import time
import logging
import hashlib
import hmac
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, ActivityLogModel, SettingsModel

logger = logging.getLogger("AutoSEM.Shopify")
router = APIRouter()

# ─── Configuration ────────────────────────────────────────────────
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")

# In-memory token cache (refreshed automatically)
_token_cache = {
    "access_token": os.environ.get("SHOPIFY_ACCESS_TOKEN", ""),
    "expires_at": 0,  # Unix timestamp
    "scopes": "",
}


# ─── Token Management ────────────────────────────────────────────

def _refresh_token() -> str:
    """Generate a fresh Shopify token via client_credentials grant.
    
    Tokens expire every ~24 hours (86,399 seconds).
    CRITICAL: Content-Type must be x-www-form-urlencoded, NOT JSON.
    """
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        logger.warning("Shopify client credentials not configured")
        return _token_cache.get("access_token", "")

    try:
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
        expires_in = data.get("expires_in", 86399)
        scopes = data.get("scope", "")

        _token_cache["access_token"] = token
        _token_cache["expires_at"] = time.time() + expires_in - 300  # 5 min buffer
        _token_cache["scopes"] = scopes

        logger.info(f"Shopify token refreshed, expires in {expires_in}s, scopes: {scopes[:80]}")
        return token

    except Exception as e:
        logger.error(f"Shopify token refresh failed: {e}")
        return _token_cache.get("access_token", "")


def _get_token() -> str:
    """Get a valid Shopify access token, refreshing if expired."""
    if time.time() >= _token_cache.get("expires_at", 0):
        return _refresh_token()
    return _token_cache.get("access_token", "")


def _api(method: str, endpoint: str, **kwargs) -> dict:
    """Make an authenticated Shopify Admin API request."""
    token = _get_token()
    if not token:
        raise HTTPException(status_code=503, detail="No Shopify token available")

    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)

    if resp.status_code == 401:
        # Token expired mid-request, force refresh and retry once
        logger.warning("Shopify 401 — forcing token refresh")
        _token_cache["expires_at"] = 0
        token = _get_token()
        headers["X-Shopify-Access-Token"] = token
        resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)

    return resp.json()


def _log_activity(db: Session, action: str, entity_id: str = "", details: str = ""):
    """Log activity to the database."""
    try:
        log = ActivityLogModel(
            action=action,
            entity_type="shopify",
            entity_id=entity_id,
            details=details,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log activity: {e}")


# ─── Request Models ───────────────────────────────────────────────

class UpdateProductRequest(BaseModel):
    product_id: int
    title: Optional[str] = None
    body_html: Optional[str] = None
    tags: Optional[str] = None
    status: Optional[str] = None  # "active" or "draft"


class UpdateProductMetafieldRequest(BaseModel):
    product_id: int
    namespace: str = "global"
    key: str
    value: str
    type: str = "single_line_text_field"


class CreateDiscountRequest(BaseModel):
    code: str  # e.g. "LASTCHANCE10"
    discount_type: str = "percentage"  # "percentage" or "fixed_amount"
    value: float = 10.0  # 10 = 10% off or $10 off
    title: Optional[str] = None
    usage_limit: Optional[int] = None  # None = unlimited
    once_per_customer: bool = True


# ─── Endpoints ────────────────────────────────────────────────────

@router.get("/status", summary="Shopify connection status")
def shopify_status():
    """Check Shopify token health and store connectivity."""
    token = _get_token()
    if not token:
        return {
            "connected": False,
            "message": "No Shopify credentials configured",
            "store": SHOPIFY_STORE,
        }

    try:
        data = _api("GET", "shop.json")
        shop = data.get("shop", {})
        return {
            "connected": True,
            "store": SHOPIFY_STORE,
            "shop_name": shop.get("name", ""),
            "domain": shop.get("domain", ""),
            "plan": shop.get("plan_display_name", ""),
            "token_expires_in": max(0, int(_token_cache["expires_at"] - time.time())),
            "scopes": _token_cache.get("scopes", ""),
        }
    except Exception as e:
        return {
            "connected": False,
            "message": str(e),
            "store": SHOPIFY_STORE,
        }


@router.post("/refresh-token", summary="Force token refresh")
def force_refresh_token():
    """Force-refresh the Shopify access token."""
    _token_cache["expires_at"] = 0
    token = _get_token()
    if token:
        return {
            "status": "refreshed",
            "token_prefix": token[:12] + "...",
            "expires_in": int(_token_cache["expires_at"] - time.time()),
            "scopes": _token_cache.get("scopes", ""),
        }
    return {"status": "error", "message": "Failed to refresh token"}


@router.get("/products", summary="List all products")
def list_products(limit: int = 50, status: str = "active"):
    """Get all products with key fields."""
    data = _api("GET", f"products.json?limit={limit}&status={status}&fields=id,title,handle,status,tags,variants,body_html")
    products = data.get("products", [])

    result = []
    for p in products:
        variants = p.get("variants", [])
        result.append({
            "id": p["id"],
            "title": p["title"],
            "handle": p["handle"],
            "status": p.get("status", ""),
            "tags": p.get("tags", ""),
            "price": variants[0].get("price", "") if variants else "",
            "has_description": len(p.get("body_html", "") or "") > 100,
            "description_length": len(p.get("body_html", "") or ""),
        })

    return {
        "status": "ok",
        "count": len(result),
        "products": result,
    }


@router.get("/products/{product_id}", summary="Get single product")
def get_product(product_id: int):
    """Get full product details."""
    try:
        data = _api("GET", f"products/{product_id}.json")
        product = data.get("product")
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"status": "ok", "product": product}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")


@router.put("/products/{product_id}", summary="Update a product")
def update_product(product_id: int, req: UpdateProductRequest, db: Session = Depends(get_db)):
    """Update product fields (title, description, tags, status)."""
    update = {}
    if req.title is not None:
        update["title"] = req.title
    if req.body_html is not None:
        update["body_html"] = req.body_html
    if req.tags is not None:
        update["tags"] = req.tags
    if req.status is not None:
        update["status"] = req.status

    if not update:
        return {"status": "error", "message": "No fields to update"}

    data = _api("PUT", f"products/{product_id}.json", json={"product": {"id": product_id, **update}})
    product = data.get("product")

    if product:
        fields_updated = list(update.keys())
        _log_activity(db, "SHOPIFY_PRODUCT_UPDATED", str(product_id),
                      f"Updated {', '.join(fields_updated)} on {product.get('title', '')}")
        return {
            "status": "updated",
            "product_id": product_id,
            "fields_updated": fields_updated,
            "title": product.get("title", ""),
        }

    return {"status": "error", "message": "Update failed", "response": data}


@router.get("/collections", summary="List all collections")
def list_collections():
    """Get all smart and custom collections."""
    smart = _api("GET", "smart_collections.json?fields=id,title,handle,rules,published_at")
    custom = _api("GET", "custom_collections.json?fields=id,title,handle,published_at")

    collections = []
    for c in smart.get("smart_collections", []):
        collections.append({
            "id": c["id"],
            "title": c["title"],
            "handle": c.get("handle", ""),
            "type": "smart",
            "rules": c.get("rules", []),
            "published": c.get("published_at") is not None,
        })
    for c in custom.get("custom_collections", []):
        collections.append({
            "id": c["id"],
            "title": c["title"],
            "handle": c.get("handle", ""),
            "type": "custom",
            "published": c.get("published_at") is not None,
        })

    return {"status": "ok", "count": len(collections), "collections": collections}


@router.get("/collections/{collection_id}/products", summary="Products in a collection")
def collection_products(collection_id: int):
    """Get products belonging to a specific collection."""
    try:
        data = _api("GET", f"collections/{collection_id}/products.json?fields=id,title,handle,status,tags")
        products = data.get("products", [])
        return {
            "status": "ok",
            "collection_id": collection_id,
            "count": len(products),
            "products": products,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Collection {collection_id} not found")


@router.get("/health-check", summary="Full store health audit")
def store_health_check():
    """Run a comprehensive health check on the store."""
    token = _get_token()
    if not token:
        return {"status": "error", "message": "No Shopify token"}

    # Get products
    products_data = _api("GET", "products.json?limit=250&status=active&fields=id,title,body_html,tags,variants")
    products = products_data.get("products", [])

    # Get collections
    smart = _api("GET", "smart_collections.json?fields=id,title,products_count,published_at")
    custom = _api("GET", "custom_collections.json?fields=id,title,published_at")

    # Analyze products
    total = len(products)
    with_description = sum(1 for p in products if len(p.get("body_html", "") or "") > 100)
    with_tags = sum(1 for p in products if p.get("tags", ""))
    price_range = []
    for p in products:
        for v in p.get("variants", []):
            try:
                price_range.append(float(v.get("price", 0)))
            except (ValueError, TypeError):
                pass

    return {
        "status": "healthy",
        "store": SHOPIFY_STORE,
        "token_valid": True,
        "token_expires_in": max(0, int(_token_cache["expires_at"] - time.time())),
        "products": {
            "total": total,
            "with_description": with_description,
            "with_tags": with_tags,
            "cro_coverage": f"{with_description}/{total}",
            "price_range": f"${min(price_range):.2f} - ${max(price_range):.2f}" if price_range else "N/A",
        },
        "collections": {
            "smart": len(smart.get("smart_collections", [])),
            "custom": len(custom.get("custom_collections", [])),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/blog-posts", summary="List blog posts")
def list_blog_posts():
    """Get all blog posts for SEO tracking."""
    blogs = _api("GET", "blogs.json?fields=id,title")
    all_posts = []

    for blog in blogs.get("blogs", []):
        blog_id = blog["id"]
        articles = _api("GET", f"blogs/{blog_id}/articles.json?fields=id,title,handle,published_at,tags")
        for a in articles.get("articles", []):
            all_posts.append({
                "id": a["id"],
                "blog_id": blog_id,
                "blog_title": blog["title"],
                "title": a["title"],
                "handle": a.get("handle", ""),
                "published_at": a.get("published_at"),
                "tags": a.get("tags", ""),
                "url": f"/blogs/{blog['title'].lower().replace(' ', '-')}/{a.get('handle', '')}",
            })

    return {"status": "ok", "count": len(all_posts), "posts": all_posts}


# ─── Discount Codes ───────────────────────────────────────────────

@router.post("/create-discount", summary="Create a discount code")
def create_discount(req: CreateDiscountRequest, db: Session = Depends(get_db)):
    """Create a Shopify discount code via Price Rules API.

    Creates a price rule then attaches a discount code to it.
    Supports percentage (e.g. 10% off) and fixed_amount (e.g. $10 off).
    """
    # Shopify price rules expect negative value for discounts
    value = -abs(req.value)

    price_rule_payload = {
        "price_rule": {
            "title": req.title or req.code,
            "target_type": "line_item",
            "target_selection": "all",
            "allocation_method": "across",
            "value_type": req.discount_type,
            "value": str(value),
            "customer_selection": "all",
            "once_per_customer": req.once_per_customer,
            "starts_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    if req.usage_limit:
        price_rule_payload["price_rule"]["usage_limit"] = req.usage_limit

    # Step 1: Create the price rule
    pr_data = _api("POST", "price_rules.json", json=price_rule_payload)
    price_rule = pr_data.get("price_rule")
    if not price_rule:
        return {"status": "error", "message": "Failed to create price rule", "response": pr_data}

    price_rule_id = price_rule["id"]

    # Step 2: Create the discount code on the price rule
    dc_data = _api("POST", f"price_rules/{price_rule_id}/discount_codes.json",
                    json={"discount_code": {"code": req.code}})
    discount_code = dc_data.get("discount_code")
    if not discount_code:
        return {"status": "error", "message": "Price rule created but discount code failed", "response": dc_data}

    _log_activity(db, "SHOPIFY_DISCOUNT_CREATED", req.code,
                  f"{req.discount_type} {abs(req.value)} | limit={req.usage_limit or 'unlimited'}")

    return {
        "status": "created",
        "code": discount_code["code"],
        "discount_type": req.discount_type,
        "value": abs(req.value),
        "price_rule_id": price_rule_id,
        "usage_limit": req.usage_limit,
        "once_per_customer": req.once_per_customer,
    }


# ─── Customers ────────────────────────────────────────────────────

@router.get("/customers", summary="List recent customers")
def list_customers(limit: int = 50):
    """Fetch recent customers with order count and total spent.

    Uses read_customers scope. Useful for Klaviyo list sync.
    """
    data = _api("GET", f"customers.json?limit={limit}&fields=id,first_name,last_name,email,orders_count,total_spent,created_at,tags")
    customers = data.get("customers", [])

    result = []
    for c in customers:
        result.append({
            "id": c["id"],
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "email": c.get("email", ""),
            "orders_count": c.get("orders_count", 0),
            "total_spent": c.get("total_spent", "0.00"),
            "created_at": c.get("created_at", ""),
            "tags": c.get("tags", ""),
        })

    return {
        "status": "ok",
        "count": len(result),
        "customers": result,
    }


# ─── Webhooks ────────────────────────────────────────────────────

@router.post("/register-webhook", summary="Manually register order webhook")
def register_webhook_manual():
    """Manually trigger Shopify orders/create webhook registration."""
    try:
        from app.services.shopify_webhook_register import register_webhooks_on_startup
        result = register_webhooks_on_startup()
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Manual webhook registration failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/webhooks", summary="List registered Shopify webhooks")
def list_registered_webhooks():
    """List all webhooks registered with Shopify for this app."""
    try:
        from app.services.shopify_webhook_register import list_webhooks
        webhooks = list_webhooks()
        return {
            "status": "ok",
            "count": len(webhooks),
            "webhooks": [
                {
                    "id": wh.get("id"),
                    "topic": wh.get("topic"),
                    "address": wh.get("address"),
                    "created_at": wh.get("created_at"),
                }
                for wh in webhooks
            ],
        }
    except Exception as e:
        logger.error(f"Failed to list webhooks: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/webhook/order-created", summary="Order created webhook",
             description="Receive Shopify order webhook, attribute revenue to campaigns via UTM/referrer")
async def webhook_order_created(request: Request, db: Session = Depends(get_db)):
    """Receive Shopify order webhook.

    Shopify sends the order as a raw JSON body (not wrapped in {"order": ...}).
    Parses order_number, total_price, line_items, customer, discount_codes,
    landing_site, referring_site, then delegates to AttributionService for
    campaign revenue attribution.
    """
    try:
        import json as _json
        body = await request.body()
        order = _json.loads(body) if body else {}
    except Exception:
        order = {}

    # Shopify may wrap or send raw — normalise
    if "order" in order and isinstance(order["order"], dict):
        order = order["order"]

    order_number = order.get("order_number") or order.get("name") or order.get("id", "unknown")
    total_price = float(order.get("total_price", 0) or 0)
    customer = order.get("customer", {}) or {}
    customer_email = customer.get("email", "")
    discount_codes = order.get("discount_codes", []) or []
    line_items = order.get("line_items", []) or []
    source_name = order.get("source_name", "")
    landing_site = order.get("landing_site", "")
    referring_site = order.get("referring_site", "")

    # Log ORDER_RECEIVED immediately (before attribution)
    _log_activity(
        db, "ORDER_RECEIVED", str(order_number),
        f"${total_price:.2f} | {len(line_items)} items | "
        f"customer={customer_email} | source={source_name} | "
        f"discounts={','.join(d.get('code','') for d in discount_codes) or 'none'} | "
        f"landing={landing_site[:80]}"
    )

    # Attribute revenue to a campaign
    from app.services.attribution import AttributionService
    attribution_svc = AttributionService(db)
    result = attribution_svc.attribute_order(order)

    # Fire Meta CAPI Purchase event (server-side conversion tracking)
    capi_result = None
    try:
        from app.services.meta_capi import get_capi_client
        capi = get_capi_client(db)
        if capi and total_price > 0:
            capi_result = capi.send_purchase(order)
            _log_activity(
                db, "CAPI_PURCHASE_SENT", str(order_number),
                f"${total_price:.2f} | pixel={capi.pixel_id} | "
                f"events_received={capi_result.get('events_received', '?')}",
            )
            logger.info(f"CAPI Purchase event sent for order {order_number}: {capi_result}")
    except Exception as e:
        logger.warning(f"CAPI Purchase event failed for order {order_number}: {e}")

    # First-sale detection: auto-exit awareness mode
    first_sale_triggered = False
    if total_price > 0:
        try:
            roas_row = db.query(SettingsModel).filter(
                SettingsModel.key == "min_roas_threshold"
            ).first()
            current_threshold = float(roas_row.value) if roas_row and roas_row.value else None
            logger.info(f"First-sale check: roas_row exists={roas_row is not None}, "
                        f"value={roas_row.value if roas_row else 'N/A'}, threshold={current_threshold}")
            if current_threshold is not None and current_threshold == 0:
                roas_row.value = "1.5"
                db.add(roas_row)
                db.commit()
                first_sale_triggered = True
                _log_activity(
                    db, "FIRST_SALE_DETECTED", str(order_number),
                    f"${total_price:.2f} | customer={customer_email} | "
                    f"items={len(line_items)} | discounts={','.join(d.get('code','') for d in discount_codes) or 'none'}"
                )
                _log_activity(
                    db, "SETTINGS_AUTO_UPDATED", "min_roas_threshold",
                    "Awareness mode OFF: min_roas_threshold changed from 0 to 1.5 (triggered by first sale)"
                )
                logger.info(f"First sale detected (order {order_number}, ${total_price:.2f}) — exited awareness mode, min_roas_threshold set to 1.5")
        except Exception as e:
            logger.error(f"First-sale detection failed: {e}", exc_info=True)

    return {
        "status": "ok",
        "order_number": order_number,
        "total_price": total_price,
        "items": len(line_items),
        "attribution": result,
        "first_sale_triggered": first_sale_triggered,
        "capi_purchase": capi_result,
    }


# ─── Checkout Audit ──────────────────────────────────────────────

@router.get("/checkout-audit", summary="Abandoned checkout audit report")
def checkout_audit(days_back: int = 30, db: Session = Depends(get_db)):
    """Analyze abandoned checkouts to diagnose conversion problems.

    With 509 ad clicks and 0 purchases, this answers WHERE visitors drop off:
    - Never reaching product pages?
    - Adding to cart but abandoning checkout?
    - Starting checkout but not completing payment?

    Returns 7-day and 30-day abandonment analysis with UTM attribution
    and actionable recommendations.
    """
    from app.services.checkout_audit import CheckoutAuditor

    auditor = CheckoutAuditor(_api)
    report = auditor.generate_report(days_back=days_back)

    _log_activity(
        db, "CHECKOUT_AUDIT_RUN", "",
        f"7d={report.get('abandoned_checkouts_7d', 0)} | "
        f"30d={report.get('abandoned_checkouts_30d', 0)} | "
        f"value_30d={report.get('abandoned_cart_value_30d', '$0')}"
    )

    return report


@router.get("/cart-recovery", summary="Get recoverable abandoned carts")
def cart_recovery(hours_back: int = 48, db: Session = Depends(get_db)):
    """Get abandoned checkouts from last N hours with recovery URLs.

    Returns carts that have a customer email and recovery URL,
    ready for Klaviyo abandoned cart recovery emails.

    Use this data to:
    1. Send targeted recovery emails via Klaviyo
    2. Identify high-value carts worth personal outreach
    3. Track which products are most frequently abandoned
    """
    from app.services.checkout_audit import CheckoutAuditor

    auditor = CheckoutAuditor(_api)
    result = auditor.get_recoverable_carts(hours_back=hours_back)

    _log_activity(
        db, "CART_RECOVERY_CHECK", "",
        f"hours={hours_back} | recoverable={result.get('recoverable_count', 0)} | "
        f"value={result.get('recoverable_value', '$0')}"
    )

    return result


# ─── Review Solicitation ─────────────────────────────────────────

JUDGEME_API_URL = "https://judge.me/api/v1"
JUDGEME_SHOP_DOMAIN = "court-sportswear.com"


def _get_judgeme_token() -> str | None:
    """Return Judge.me private API token from env."""
    return os.environ.get("JUDGEME_API_TOKEN")


@router.get("/review-candidates", summary="Find customers eligible for review requests")
def review_candidates(days_back: int = 90, db: Session = Depends(get_db)):
    """Fetch fulfilled orders and extract unique customers with products purchased.

    Returns customers who received their order and haven't been asked for a review,
    with days_since_fulfillment so you can prioritize recent buyers.
    """
    from datetime import timedelta

    token = _get_token(db)
    if not token:
        return {"error": "No Shopify token available"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    # Fetch fulfilled orders
    orders = []
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json"
    params = {
        "status": "any",
        "fulfillment_status": "fulfilled",
        "created_at_min": cutoff,
        "limit": 250,
        "fields": "id,email,created_at,fulfillments,line_items,customer",
    }
    headers = {"X-Shopify-Access-Token": token}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
    except Exception as e:
        return {"error": f"Failed to fetch orders: {e}"}

    # Build unique customer → products map
    candidates = {}
    now = datetime.now(timezone.utc)

    for order in orders:
        email = order.get("email", "").lower().strip()
        if not email:
            continue

        customer = order.get("customer", {}) or {}
        first_name = customer.get("first_name", "")
        last_name = customer.get("last_name", "")

        # Get fulfillment date
        fulfillments = order.get("fulfillments", [])
        fulfilled_at = None
        for f in fulfillments:
            if f.get("status") == "success" and f.get("created_at"):
                fulfilled_at = f["created_at"]
                break

        if not fulfilled_at:
            continue

        try:
            ful_dt = datetime.fromisoformat(fulfilled_at.replace("Z", "+00:00"))
            days_since = (now - ful_dt).days
        except Exception:
            days_since = None

        products = []
        for item in order.get("line_items", []):
            products.append({
                "product_id": item.get("product_id"),
                "title": item.get("title"),
                "variant_title": item.get("variant_title"),
            })

        if email not in candidates:
            candidates[email] = {
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "orders": [],
                "products": [],
                "earliest_fulfillment_days_ago": days_since,
            }

        candidates[email]["orders"].append({
            "order_id": order.get("id"),
            "fulfilled_at": fulfilled_at,
            "days_since": days_since,
        })
        candidates[email]["products"].extend(products)

        if days_since is not None:
            existing = candidates[email]["earliest_fulfillment_days_ago"]
            if existing is None or days_since < existing:
                candidates[email]["earliest_fulfillment_days_ago"] = days_since

    # Deduplicate products per customer
    for c in candidates.values():
        seen = set()
        unique = []
        for p in c["products"]:
            pid = p.get("product_id")
            if pid and pid not in seen:
                seen.add(pid)
                unique.append(p)
        c["products"] = unique

    candidate_list = sorted(candidates.values(), key=lambda x: x.get("earliest_fulfillment_days_ago") or 999)

    _log_activity(db, "REVIEW_CANDIDATES_CHECK", "", f"Found {len(candidate_list)} review candidates from last {days_back} days")

    return {
        "total_candidates": len(candidate_list),
        "days_back": days_back,
        "candidates": candidate_list,
    }


@router.post("/request-reviews", summary="Trigger review request emails via Judge.me or Klaviyo")
def request_reviews(
    emails: list[str] | None = None,
    send_all: bool = False,
    db: Session = Depends(get_db),
):
    """Send review request emails to fulfilled-order customers.

    - If Judge.me API token is set (JUDGEME_API_TOKEN env), uses Judge.me API
    - Falls back to Klaviyo transactional email
    - Pass specific emails or set send_all=True for all candidates
    """
    # Get candidates first
    candidates_resp = review_candidates(days_back=90, db=db)
    if "error" in candidates_resp:
        return candidates_resp

    all_candidates = candidates_resp.get("candidates", [])
    if not all_candidates:
        return {"status": "no_candidates", "message": "No fulfilled orders found to request reviews for"}

    # Filter to requested emails
    if emails and not send_all:
        target_candidates = [c for c in all_candidates if c["email"] in [e.lower().strip() for e in emails]]
    else:
        target_candidates = all_candidates

    if not target_candidates:
        return {"status": "no_matches", "message": "None of the provided emails matched review candidates"}

    judgeme_token = _get_judgeme_token()
    results = {"sent": [], "failed": [], "method": "judge.me" if judgeme_token else "klaviyo"}

    for candidate in target_candidates:
        email = candidate["email"]
        first_name = candidate.get("first_name", "Customer")
        products = candidate.get("products", [])

        if not products:
            results["failed"].append({"email": email, "reason": "No products found"})
            continue

        # Use first product for review request
        product = products[0]

        if judgeme_token:
            # Judge.me review request API
            try:
                payload = {
                    "shop_domain": JUDGEME_SHOP_DOMAIN,
                    "platform": "shopify",
                    "name": first_name,
                    "email": email,
                    "id": product.get("product_id"),
                }
                resp = requests.post(
                    f"{JUDGEME_API_URL}/reviews/request",
                    json=payload,
                    headers={"Authorization": f"Bearer {judgeme_token}"},
                    timeout=10,
                )
                if resp.status_code in (200, 201, 202):
                    results["sent"].append({
                        "email": email,
                        "product": product.get("title"),
                        "method": "judge.me",
                    })
                else:
                    results["failed"].append({
                        "email": email,
                        "reason": f"Judge.me {resp.status_code}: {resp.text[:200]}",
                    })
            except Exception as e:
                results["failed"].append({"email": email, "reason": f"Judge.me error: {e}"})
        else:
            # Klaviyo fallback — send review request via transactional email
            try:
                from app.database import SettingsModel
                key_row = db.query(SettingsModel).filter(SettingsModel.key == "klaviyo_api_key").first()
                klaviyo_key = key_row.value if key_row else os.environ.get("KLAVIYO_PRIVATE_KEY")

                if not klaviyo_key:
                    results["failed"].append({"email": email, "reason": "No Klaviyo API key configured"})
                    continue

                review_url = f"https://{JUDGEME_SHOP_DOMAIN}/pages/review"
                payload = {
                    "data": {
                        "type": "event",
                        "attributes": {
                            "profile": {
                                "data": {
                                    "type": "profile",
                                    "attributes": {
                                        "email": email,
                                        "first_name": first_name,
                                    },
                                },
                            },
                            "metric": {
                                "data": {
                                    "type": "metric",
                                    "attributes": {
                                        "name": "Review Request Sent",
                                    },
                                },
                            },
                            "properties": {
                                "product_name": product.get("title", "your recent purchase"),
                                "review_url": review_url,
                                "first_name": first_name,
                            },
                            "time": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                }
                resp = requests.post(
                    "https://a.klaviyo.com/api/events",
                    json=payload,
                    headers={
                        "Authorization": f"Klaviyo-API-Key {klaviyo_key}",
                        "revision": "2024-10-15",
                        "Content-Type": "application/json",
                    },
                    timeout=10,
                )
                if resp.status_code in (200, 201, 202):
                    results["sent"].append({
                        "email": email,
                        "product": product.get("title"),
                        "method": "klaviyo",
                    })
                else:
                    results["failed"].append({
                        "email": email,
                        "reason": f"Klaviyo {resp.status_code}: {resp.text[:200]}",
                    })
            except Exception as e:
                results["failed"].append({"email": email, "reason": f"Klaviyo error: {e}"})

    _log_activity(
        db, "REVIEW_REQUESTS_SENT", "",
        f"Sent {len(results['sent'])}/{len(target_candidates)} review requests via {results['method']}"
    )

    return {
        "status": "ok",
        "method": results["method"],
        "total_targeted": len(target_candidates),
        "sent_count": len(results["sent"]),
        "failed_count": len(results["failed"]),
        "sent": results["sent"],
        "failed": results["failed"],
    }


@router.post("/seed-reviews", summary="Get instructions for seeding real reviews with incentives")
def seed_reviews(db: Session = Depends(get_db)):
    """Return a structured plan for getting real reviews from existing customers.

    Does NOT create fake reviews. Provides:
    - Prioritized customer list (most recent fulfilled orders first)
    - Discount code creation for photo review incentive (15% off)
    - Email template suggestions
    - Judge.me configuration tips
    """
    token = _get_token(db)
    discount_code = None

    # Try to create a discount code for photo review incentive
    if token:
        try:
            payload = {
                "price_rule": {
                    "title": "PHOTOREVIEW15",
                    "target_type": "line_item",
                    "target_selection": "all",
                    "allocation_method": "across",
                    "value_type": "percentage",
                    "value": "-15.0",
                    "customer_selection": "all",
                    "starts_at": datetime.now(timezone.utc).isoformat(),
                    "usage_limit": 50,
                }
            }
            resp = requests.post(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/price_rules.json",
                json=payload,
                headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                rule_id = resp.json().get("price_rule", {}).get("id")
                if rule_id:
                    dc_payload = {"discount_code": {"code": "PHOTOREVIEW15"}}
                    dc_resp = requests.post(
                        f"https://{SHOPIFY_STORE}/admin/api/2024-01/price_rules/{rule_id}/discount_codes.json",
                        json=dc_payload,
                        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                        timeout=10,
                    )
                    if dc_resp.status_code in (200, 201):
                        discount_code = "PHOTOREVIEW15"
            elif resp.status_code == 422:
                # Price rule might already exist
                discount_code = "PHOTOREVIEW15"
        except Exception as e:
            logger.warning(f"Discount code creation failed: {e}")

    # Get candidates for the instruction plan
    candidates_resp = review_candidates(days_back=90, db=db)
    candidate_list = candidates_resp.get("candidates", []) if "error" not in candidates_resp else []

    plan = {
        "status": "ok",
        "overview": (
            f"You have {len(candidate_list)} customers who received orders in the last 90 days. "
            "Zero reviews are currently live on the store. Here's the plan to seed real reviews."
        ),
        "discount_code": discount_code,
        "discount_details": "15% off next order for customers who leave a photo review (code: PHOTOREVIEW15, limit: 50 uses)" if discount_code else "Set SHOPIFY_ACCESS_TOKEN to auto-create discount code",
        "steps": [
            {
                "step": 1,
                "action": "Configure Judge.me review request emails",
                "details": (
                    "In Shopify Admin → Apps → Judge.me → Settings → Email, enable automatic review request emails. "
                    "Set timing to 14 days after fulfillment. Customize the email template to mention the 15% photo review discount."
                ),
            },
            {
                "step": 2,
                "action": "Send manual review requests to recent customers",
                "details": (
                    f"Call POST /api/v1/shopify/request-reviews with send_all=true to trigger review request emails "
                    f"to all {len(candidate_list)} customers. Or pass specific emails to target high-value customers first."
                ),
                "api_call": "POST /api/v1/shopify/request-reviews?send_all=true",
            },
            {
                "step": 3,
                "action": "Prioritize customers who ordered 7-30 days ago",
                "details": (
                    "These customers have had time to use the product but the experience is still fresh. "
                    "They are most likely to leave a detailed, authentic review."
                ),
                "priority_customers": [
                    {"email": c["email"], "name": f"{c['first_name']} {c['last_name']}".strip(), "days_ago": c.get("earliest_fulfillment_days_ago")}
                    for c in candidate_list
                    if c.get("earliest_fulfillment_days_ago") and 7 <= c["earliest_fulfillment_days_ago"] <= 30
                ][:10],
            },
            {
                "step": 4,
                "action": "Offer photo review incentive",
                "details": (
                    f"{'Discount code PHOTOREVIEW15 has been created (15% off, 50 uses).' if discount_code else 'Create a discount code for photo reviewers.'} "
                    "Mention in the review request email: 'Share a photo of you wearing your Court Sportswear and get 15% off your next order!'"
                ),
            },
            {
                "step": 5,
                "action": "Follow up personally with top customers",
                "details": (
                    "For your highest-value or repeat customers, send a personal email (not automated) asking for a review. "
                    "Personal outreach converts at 3-5x the rate of automated emails."
                ),
            },
        ],
        "email_template": {
            "subject": "How are you liking your Court Sportswear? 🎾",
            "body": (
                "Hi {first_name},\n\n"
                "We hope you're loving your {product_name}! As a small, family-run tennis & pickleball brand, "
                "your feedback means the world to us.\n\n"
                "Would you mind taking 30 seconds to leave a quick review? "
                "If you include a photo, we'll send you 15% off your next order as a thank you.\n\n"
                "Just click here to leave your review: {review_url}\n\n"
                "Thanks for being part of the Court Sportswear family!\n"
                "— The Court Sportswear Team"
            ),
        },
        "expected_results": {
            "typical_review_request_conversion": "5-15%",
            "with_photo_incentive": "10-20%",
            "estimated_reviews_from_29_customers": "3-6 reviews",
            "impact": "Even 3-5 reviews with photos can increase conversion rate by 20-30%",
        },
    }

    _log_activity(db, "SEED_REVIEWS_PLAN", "", f"Generated review seeding plan for {len(candidate_list)} customers, discount={'created' if discount_code else 'skipped'}")

    return plan
