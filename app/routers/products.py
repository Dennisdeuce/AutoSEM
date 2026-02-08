"""
Products API router - Shopify product sync and management
"""

import os
import json
import logging
from typing import List

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, ProductModel
from app.schemas import Product, ProductCreate

logger = logging.getLogger("AutoSEM.Products")
router = APIRouter()


@router.get("/", response_model=List[Product])
def read_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(ProductModel).offset(skip).limit(limit).all()


@router.post("/", response_model=Product)
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(ProductModel).filter(ProductModel.shopify_id == product.shopify_id).first()
    if existing:
        for key, val in product.dict(exclude_unset=True).items():
            setattr(existing, key, val)
        db.commit()
        db.refresh(existing)
        return existing

    db_product = ProductModel(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.get("/{product_id}", response_model=Product)
def read_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/sync-shopify", summary="Sync Shopify Products",
             description="Sync products from Shopify store")
def sync_shopify_products(db: Session = Depends(get_db)):
    """Pull all products from Shopify and upsert into local DB"""
    shop_url = os.environ.get("SHOPIFY_STORE_URL", "court-sportswear.myshopify.com")
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")

    if not access_token:
        return {"status": "error", "message": "SHOPIFY_ACCESS_TOKEN not configured"}

    headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}
    url = f"https://{shop_url}/admin/api/2024-01/products.json?limit=250"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        products = resp.json().get("products", [])

        synced = 0
        for p in products:
            images_str = ",".join([img["src"] for img in p.get("images", [])])
            variants_str = str(p.get("variants", []))
            tags_str = p.get("tags", "")
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
                existing.tags = tags_str
                existing.is_available = p.get("status") == "active"
            else:
                db_product = ProductModel(
                    shopify_id=str(p["id"]),
                    title=p["title"],
                    description=p.get("body_html", ""),
                    handle=p.get("handle", ""),
                    product_type=p.get("product_type", ""),
                    vendor=p.get("vendor", ""),
                    price=price,
                    images=images_str,
                    variants=variants_str,
                    tags=tags_str,
                    is_available=p.get("status") == "active",
                )
                db.add(db_product)
            synced += 1

        db.commit()
        logger.info(f"Synced {synced} products from Shopify")
        return {"status": "success", "synced": synced}

    except Exception as e:
        logger.error(f"Shopify sync failed: {e}")
        return {"status": "error", "message": str(e)}
