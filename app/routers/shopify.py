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
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, ActivityLogModel

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
    data = _api("GET", f"products/{product_id}.json")
    product = data.get("product")
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "ok", "product": product}


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
    data = _api("GET", f"collections/{collection_id}/products.json?fields=id,title,handle,status,tags")
    products = data.get("products", [])
    return {
        "status": "ok",
        "collection_id": collection_id,
        "count": len(products),
        "products": products,
    }


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
def webhook_order_created(payload: dict, db: Session = Depends(get_db)):
    """
    When an order comes in, delegate to AttributionService to parse UTMs
    and attribute revenue to the correct campaign.
    """
    from app.services.attribution import AttributionService

    order = payload.get("order", payload)  # Handle both wrapped and raw payloads
    attribution_svc = AttributionService(db)
    result = attribution_svc.attribute_order(order)

    return {"status": "ok", "attribution": result}
