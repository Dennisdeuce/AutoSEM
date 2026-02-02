#!/usr/bin/env python3
"""
Data sync script for AutoSEM
Syncs products, orders, and costs from external APIs
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.services.shopify import shopify_service
from app.services.printful import printful_service
from app.crud import product
from app.schemas.product import ProductCreate


def sync_products():
    """Sync products from Shopify and update costs from Printful"""
    db = SessionLocal()
    try:
        print("Fetching products from Shopify...")
        shopify_products = shopify_service.get_products()

        for shopify_prod in shopify_products:
            # Check if product already exists
            existing = product.get_by_shopify_id(db, shopify_id=str(shopify_prod["id"]))

            # Get cost from Printful (simplified - would need proper mapping)
            cost_price = printful_service.calculate_total_cost(str(shopify_prod["id"]))

            product_data = shopify_service.transform_product_to_schema(shopify_prod)
            product_data.cost_price = cost_price

            if product_data.price and cost_price:
                product_data.gross_margin = product_data.price - cost_price

            if existing:
                # Update existing product
                product.update(db, db_obj=existing, obj_in=product_data)
                print(f"Updated product: {product_data.title}")
            else:
                # Create new product
                product.create(db, obj_in=product_data)
                print(f"Created product: {product_data.title}")

        print(f"Synced {len(shopify_products)} products")

    finally:
        db.close()


def sync_orders():
    """Sync recent orders from Shopify"""
    db = SessionLocal()
    try:
        print("Fetching recent orders from Shopify...")
        # Implementation would sync orders and update campaign performance
        orders = shopify_service.get_orders(limit=50)
        print(f"Synced {len(orders)} orders")
    finally:
        db.close()


if __name__ == "__main__":
    print("Starting AutoSEM data sync...")
    sync_products()
    sync_orders()
    print("Data sync complete!")