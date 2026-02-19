"""Shopify Admin API router with auto-refreshing client_credentials tokens.

Tokens expire every 24h. This module generates a fresh token before each
API call using the client_credentials OAuth flow, so no manual rotation needed.

Required Replit Secrets:
  SHOPIFY_CLIENT_ID      - Custom app client ID
  SHOPIFY_CLIENT_SECRET  - Custom app client secret (shpss_...)
  SHOPIFY_STORE          - myshopify domain (e.g. 4448da-3.myshopify.com)
"""

import os
import time
import logging
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("AutoSEM.Shopify")
router = APIRouter()

# ---------------------------------------------------------------------------
# Token cache — reuse until 1h before expiry
# ---------------------------------------------------------------------------

_token_cache: dict = {"token": None, "expires_at": 0}

SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
API_VERSION = "2025-01"


def _get_token() -> str:
    """Get a valid Shopify Admin API token, refreshing if needed."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 3600:
        return _token_cache["token"]

    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET must be set",
        )

    resp = requests.post(
        f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
        data={
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )

    if resp.status_code != 200:
        logger.error(f"Token exchange failed ({resp.status_code}): {resp.text}")
        raise HTTPException(status_code=502, detail="Shopify token exchange failed")

    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", 86400)

    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in
    logger.info(f"Shopify token refreshed, expires in {expires_in}s, scopes: {data.get('scope', 'n/a')}")
    return token


def _api(method: str, path: str, json_body: dict = None) -> dict:
    """Make an authenticated Shopify Admin API call."""
    token = _get_token()
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/{path}"
    resp = requests.request(
        method, url,
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        json=json_body,
        timeout=30,
    )
    if resp.status_code == 401:
        # Token may have been revoked — force refresh and retry once
        _token_cache["token"] = None
        token = _get_token()
        resp = requests.request(
            method, url,
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            json=json_body,
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class TagsUpdate(BaseModel):
    product_id: int
    tags: str  # comma-separated tag string


class DescriptionUpdate(BaseModel):
    product_id: int
    body_html: str


class ProductUpdate(BaseModel):
    product_id: int
    tags: Optional[str] = None
    body_html: Optional[str] = None
    title: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", summary="Shopify connection status")
def shopify_status():
    """Check Shopify connection and token validity."""
    try:
        token = _get_token()
        return {
            "connected": True,
            "store": SHOPIFY_STORE,
            "api_version": API_VERSION,
            "token_prefix": token[:12] + "...",
            "expires_at": _token_cache["expires_at"],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/products", summary="List all Shopify products")
def list_products(limit: int = 50):
    """Fetch products directly from Shopify Admin API."""
    data = _api("GET", f"products.json?limit={limit}&fields=id,title,tags,status,handle,body_html")
    products = data.get("products", [])
    return {
        "count": len(products),
        "products": [
            {
                "id": p["id"],
                "title": p["title"],
                "handle": p.get("handle"),
                "tags": p.get("tags", ""),
                "status": p.get("status"),
                "body_html_length": len(p.get("body_html") or ""),
            }
            for p in products
        ],
    }


@router.get("/products/{product_id}", summary="Get a single product")
def get_product(product_id: int):
    """Fetch a single product with full details."""
    data = _api("GET", f"products/{product_id}.json")
    return data.get("product", {})


@router.put("/products/{product_id}/tags", summary="Update product tags")
def update_tags(product_id: int, body: TagsUpdate):
    """Update tags on a product."""
    data = _api("PUT", f"products/{product_id}.json", {
        "product": {"id": product_id, "tags": body.tags}
    })
    p = data.get("product", {})
    return {"success": True, "id": p.get("id"), "tags": p.get("tags")}


@router.put("/products/{product_id}/description", summary="Update product description")
def update_description(product_id: int, body: DescriptionUpdate):
    """Update body_html on a product."""
    data = _api("PUT", f"products/{product_id}.json", {
        "product": {"id": product_id, "body_html": body.body_html}
    })
    p = data.get("product", {})
    return {
        "success": True,
        "id": p.get("id"),
        "title": p.get("title"),
        "body_html_length": len(p.get("body_html") or ""),
    }


@router.put("/products/{product_id}", summary="Update product (tags, description, title)")
def update_product(product_id: int, body: ProductUpdate):
    """Update multiple fields on a product at once."""
    update = {"id": product_id}
    if body.tags is not None:
        update["tags"] = body.tags
    if body.body_html is not None:
        update["body_html"] = body.body_html
    if body.title is not None:
        update["title"] = body.title

    data = _api("PUT", f"products/{product_id}.json", {"product": update})
    p = data.get("product", {})
    return {
        "success": True,
        "id": p.get("id"),
        "title": p.get("title"),
        "tags": p.get("tags"),
        "body_html_length": len(p.get("body_html") or ""),
    }


@router.get("/collections", summary="List all collections")
def list_collections():
    """List smart and custom collections."""
    smart = _api("GET", "smart_collections.json?fields=id,title,rules")
    custom = _api("GET", "custom_collections.json?fields=id,title")
    return {
        "smart_collections": smart.get("smart_collections", []),
        "custom_collections": custom.get("custom_collections", []),
    }


@router.post("/sync", summary="Sync products to local DB")
def sync_to_db():
    """Fetch all products from Shopify and sync to local database."""
    from sqlalchemy.orm import Session
    from app.database import get_db, ProductModel

    db: Session = next(get_db())
    try:
        data = _api("GET", "products.json?limit=250")
        products = data.get("products", [])
        synced = 0

        for p in products:
            images_str = ",".join([img["src"] for img in p.get("images", [])])
            variants_str = str(p.get("variants", []))
            price = float(p["variants"][0]["price"]) if p.get("variants") else None

            existing = db.query(ProductModel).filter(
                ProductModel.shopify_id == str(p["id"])
            ).first()

            if existing:
                existing.title = p["title"]
                existing.description = p.get("body_html", "")
                existing.handle = p.get("handle", "")
                existing.product_type = p.get("product_type", "")
                existing.vendor = p.get("vendor", "")
                existing.price = price
                existing.images = images_str
                existing.variants = variants_str
                existing.tags = p.get("tags", "")
                existing.is_available = p.get("status") == "active"
            else:
                db.add(ProductModel(
                    shopify_id=str(p["id"]),
                    title=p["title"],
                    description=p.get("body_html", ""),
                    handle=p.get("handle", ""),
                    product_type=p.get("product_type", ""),
                    vendor=p.get("vendor", ""),
                    price=price,
                    images=images_str,
                    variants=variants_str,
                    tags=p.get("tags", ""),
                    is_available=p.get("status") == "active",
                ))
            synced += 1

        db.commit()
        logger.info(f"Synced {synced} products from Shopify")
        return {"success": True, "synced": synced}
    except Exception as e:
        db.rollback()
        logger.error(f"Shopify sync failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()
