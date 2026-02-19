"""SEO Router - JSON-LD Structured Data & XML Sitemap

Generates Schema.org Product markup and sitemaps from Shopify data.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.jsonld_generator import generate_product_jsonld, generate_all_jsonld
from app.services.sitemap import generate_sitemap

logger = logging.getLogger("AutoSEM.SEO")
router = APIRouter()


def _shopify_api(method: str, endpoint: str) -> dict:
    """Proxy to the Shopify router's _api helper."""
    from app.routers.shopify import _api
    return _api(method, endpoint)


# ─── JSON-LD ─────────────────────────────────────────────────────

@router.get("/product-jsonld/{shopify_id}", summary="Product JSON-LD",
            description="Get Schema.org Product structured data for a single product")
def product_jsonld(shopify_id: int):
    try:
        data = _shopify_api("GET", f"products/{shopify_id}.json")
        product = data.get("product")
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        jsonld = generate_product_jsonld(product)
        return {"status": "ok", "shopify_id": shopify_id, "jsonld": jsonld}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate JSON-LD for {shopify_id}: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/all-jsonld", summary="All products JSON-LD",
            description="Get Schema.org Product structured data for all active products")
def all_products_jsonld():
    try:
        data = _shopify_api(
            "GET",
            "products.json?limit=250&status=active"
            "&fields=id,title,handle,body_html,product_type,status,variants,images,image",
        )
        products = data.get("products", [])
        jsonld_list = generate_all_jsonld(products)
        return {
            "status": "ok",
            "count": len(jsonld_list),
            "products": jsonld_list,
        }
    except Exception as e:
        logger.error(f"Failed to generate all JSON-LD: {e}")
        return {"status": "error", "message": str(e)}


# ─── Sitemap ─────────────────────────────────────────────────────

@router.get("/sitemap.xml", summary="XML Sitemap",
            description="Generate an XML sitemap from Shopify products, collections, and blog posts")
def xml_sitemap():
    try:
        # Fetch products
        prod_data = _shopify_api(
            "GET",
            "products.json?limit=250&status=active&fields=id,handle,updated_at,published_at",
        )
        products = prod_data.get("products", [])

        # Fetch collections
        smart = _shopify_api("GET", "smart_collections.json?fields=id,title,handle")
        custom = _shopify_api("GET", "custom_collections.json?fields=id,title,handle")
        collections = smart.get("smart_collections", []) + custom.get("custom_collections", [])

        # Fetch blog posts
        blog_posts = []
        try:
            blogs = _shopify_api("GET", "blogs.json?fields=id,title")
            for blog in blogs.get("blogs", []):
                articles = _shopify_api(
                    "GET",
                    f"blogs/{blog['id']}/articles.json?fields=id,title,handle,published_at",
                )
                for a in articles.get("articles", []):
                    a["blog_title"] = blog["title"]
                    blog_posts.append(a)
        except Exception as e:
            logger.warning(f"Blog posts fetch failed (non-fatal): {e}")

        xml = generate_sitemap(products, collections, blog_posts)
        return Response(content=xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Sitemap generation failed: {e}")
        return Response(
            content=f'<?xml version="1.0"?><error>{e}</error>',
            media_type="application/xml",
            status_code=500,
        )
