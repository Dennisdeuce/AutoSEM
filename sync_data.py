"""
AutoSEM Data Sync
Utility for syncing product and campaign data from external sources.
"""
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autosem.sync")


def sync_shopify_products():
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/products/sync-shopify", timeout=60)
        data = response.json()
        logger.info(f"Shopify sync: {data}")
        return data
    except Exception as e:
        logger.error(f"Shopify sync failed: {e}")
        return None


def sync_google_performance():
    try:
        import httpx
        base_url = os.getenv("AUTOSEM_BASE_URL", "http://localhost:8000")
        response = httpx.post(f"{base_url}/api/automation/sync-performance", timeout=60)
        data = response.json()
        logger.info(f"Google performance sync: {data}")
        return data
    except Exception as e:
        logger.error(f"Google sync failed: {e}")
        return None


def full_sync():
    logger.info(f"Starting full sync at {datetime.utcnow().isoformat()}")
    products = sync_shopify_products()
    performance = sync_google_performance()
    logger.info("Full sync complete")
    return {"products": products, "performance": performance}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "products":
            sync_shopify_products()
        elif cmd == "performance":
            sync_google_performance()
        else:
            full_sync()
    else:
        full_sync()
