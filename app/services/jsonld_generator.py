"""JSON-LD Structured Data Generator

Generates Schema.org Product markup for Shopify products.
Used by the SEO router to serve structured data for search engines.
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("autosem.jsonld")

STORE_URL = "https://court-sportswear.com"
BRAND_NAME = "Court Sportswear"


def generate_product_jsonld(product: dict) -> dict:
    """Generate Schema.org Product JSON-LD from a Shopify product dict.

    Expects the raw Shopify product format with variants, images, etc.
    """
    variants = product.get("variants", [])
    images = product.get("images", [])

    # Price range from variants
    prices = []
    for v in variants:
        try:
            prices.append(float(v.get("price", 0)))
        except (ValueError, TypeError):
            pass

    low_price = min(prices) if prices else 0
    high_price = max(prices) if prices else 0

    # Primary image
    image_url = ""
    if images:
        image_url = images[0].get("src", "")
    elif product.get("image"):
        image_url = product["image"].get("src", "")

    # All image URLs
    all_images = [img.get("src", "") for img in images if img.get("src")]

    # SKU from first variant
    sku = ""
    if variants:
        sku = variants[0].get("sku", "") or ""

    # Availability
    available = product.get("status", "active") == "active"
    inventory_total = sum(v.get("inventory_quantity", 0) for v in variants)
    if inventory_total <= 0:
        availability = "https://schema.org/OutOfStock"
    elif available:
        availability = "https://schema.org/InStock"
    else:
        availability = "https://schema.org/Discontinued"

    # Build offers
    if low_price == high_price or len(variants) <= 1:
        offers = {
            "@type": "Offer",
            "url": f"{STORE_URL}/products/{product.get('handle', '')}",
            "priceCurrency": "USD",
            "price": f"{low_price:.2f}",
            "availability": availability,
            "seller": {"@type": "Organization", "name": BRAND_NAME},
        }
    else:
        offers = {
            "@type": "AggregateOffer",
            "url": f"{STORE_URL}/products/{product.get('handle', '')}",
            "priceCurrency": "USD",
            "lowPrice": f"{low_price:.2f}",
            "highPrice": f"{high_price:.2f}",
            "offerCount": len(variants),
            "availability": availability,
        }

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.get("title", ""),
        "url": f"{STORE_URL}/products/{product.get('handle', '')}",
        "brand": {"@type": "Brand", "name": BRAND_NAME},
        "offers": offers,
    }

    # Optional fields
    description = product.get("body_html", "") or ""
    # Strip HTML tags for plain text description
    import re
    plain = re.sub(r"<[^>]+>", " ", description).strip()
    if plain:
        jsonld["description"] = plain[:5000]

    if image_url:
        jsonld["image"] = all_images if len(all_images) > 1 else image_url

    if sku:
        jsonld["sku"] = sku

    if product.get("product_type"):
        jsonld["category"] = product["product_type"]

    return jsonld


def generate_all_jsonld(products: List[dict]) -> List[dict]:
    """Generate JSON-LD for a list of Shopify products."""
    results = []
    for p in products:
        try:
            results.append(generate_product_jsonld(p))
        except Exception as e:
            logger.warning(f"Failed to generate JSON-LD for product {p.get('id')}: {e}")
    return results
