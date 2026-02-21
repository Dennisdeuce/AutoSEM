"""AutoSEM Data Sync
Utility for syncing product and campaign data from external sources.

Fixed in Phase 14:
- /api/ paths updated to /api/v1/ (was causing 404s)
- Added Meta performance sync
- Added retry logic with exponential backoff
- Default base URL points to Replit deployment
- Added --dry-run support
"""
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autosem.sync")

DEFAULT_BASE_URL = "https://auto-sem.replit.app"
MAX_RETRIES = 3


def _api_call(method, url, timeout=60, retries=MAX_RETRIES):
    """Make an API call with retry logic and exponential backoff."""
    import httpx
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "POST":
                response = httpx.post(url, timeout=timeout)
            else:
                response = httpx.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            logger.info(f"  OK ({response.status_code}): {url}")
            return data
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning(f"  Attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt < retries:
                logger.info(f"  Retrying in {wait}s...")
                time.sleep(wait)
    logger.error(f"  FAILED after {retries} attempts: {url} — {last_error}")
    return None


def sync_shopify_products(base_url, dry_run=False):
    """Sync products from Shopify store."""
    url = f"{base_url}/api/v1/products/sync-shopify"
    logger.info(f"Syncing Shopify products: POST {url}")
    if dry_run:
        logger.info("  [DRY RUN] Would call POST %s", url)
        return {"dry_run": True}
    return _api_call("POST", url)


def sync_meta_performance(base_url, dry_run=False):
    """Sync performance data from Meta Ads."""
    url = f"{base_url}/api/v1/dashboard/sync-performance"
    logger.info(f"Syncing Meta performance: POST {url}")
    if dry_run:
        logger.info("  [DRY RUN] Would call POST %s", url)
        return {"dry_run": True}
    return _api_call("POST", url)


def sync_google_performance(base_url, dry_run=False):
    """Sync performance data from Google Ads."""
    url = f"{base_url}/api/v1/automation/sync-performance"
    logger.info(f"Syncing Google performance: POST {url}")
    if dry_run:
        logger.info("  [DRY RUN] Would call POST %s", url)
        return {"dry_run": True}
    return _api_call("POST", url)


def full_sync(base_url=None, dry_run=False):
    """Run a full data sync across all platforms."""
    if base_url is None:
        base_url = os.getenv("AUTOSEM_BASE_URL", DEFAULT_BASE_URL)

    logger.info(f"=== Full sync starting at {datetime.utcnow().isoformat()} ===")
    logger.info(f"Base URL: {base_url}")
    if dry_run:
        logger.info("MODE: DRY RUN (no API calls will be made)")

    results = {}
    results["products"] = sync_shopify_products(base_url, dry_run)
    results["meta_performance"] = sync_meta_performance(base_url, dry_run)
    results["google_performance"] = sync_google_performance(base_url, dry_run)

    succeeded = sum(1 for v in results.values() if v is not None)
    total = len(results)
    logger.info(f"=== Full sync complete: {succeeded}/{total} succeeded ===")
    return results


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    base_url = os.getenv("AUTOSEM_BASE_URL", DEFAULT_BASE_URL)

    if args:
        cmd = args[0]
        if cmd == "products":
            sync_shopify_products(base_url, dry_run)
        elif cmd == "meta":
            sync_meta_performance(base_url, dry_run)
        elif cmd == "performance":
            sync_google_performance(base_url, dry_run)
        else:
            logger.error(f"Unknown command: {cmd}")
            logger.info("Usage: python sync_data.py [products|meta|performance] [--dry-run]")
    else:
        full_sync(base_url, dry_run)
