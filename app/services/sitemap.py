"""XML Sitemap Generator

Builds a sitemap.xml from Shopify products, collections, and blog posts.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

logger = logging.getLogger("autosem.sitemap")

STORE_URL = "https://court-sportswear.com"


def _add_url(urlset: Element, loc: str, lastmod: Optional[str] = None,
             changefreq: str = "weekly", priority: str = "0.5"):
    """Add a <url> entry to the urlset."""
    url_el = SubElement(urlset, "url")
    SubElement(url_el, "loc").text = loc
    if lastmod:
        SubElement(url_el, "lastmod").text = lastmod[:10]  # YYYY-MM-DD
    SubElement(url_el, "changefreq").text = changefreq
    SubElement(url_el, "priority").text = priority


def generate_sitemap(products: List[dict], collections: List[dict],
                     blog_posts: List[dict]) -> str:
    """Generate a full sitemap.xml string.

    Args:
        products: Shopify product dicts (need handle, updated_at)
        collections: Collection dicts (need handle, type)
        blog_posts: Blog post dicts (need blog_title, handle, published_at)
    """
    urlset = Element("urlset")
    urlset.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Homepage
    _add_url(urlset, STORE_URL, lastmod=today, changefreq="daily", priority="1.0")

    # Collections
    for c in collections:
        handle = c.get("handle", "")
        if handle:
            _add_url(urlset, f"{STORE_URL}/collections/{handle}",
                     changefreq="weekly", priority="0.8")

    # Products
    for p in products:
        handle = p.get("handle", "")
        if not handle:
            continue
        lastmod = p.get("updated_at") or p.get("published_at")
        _add_url(urlset, f"{STORE_URL}/products/{handle}",
                 lastmod=lastmod, changefreq="weekly", priority="0.7")

    # Blog posts
    for post in blog_posts:
        blog_handle = (post.get("blog_title", "") or "news").lower().replace(" ", "-")
        post_handle = post.get("handle", "")
        if not post_handle:
            continue
        _add_url(urlset, f"{STORE_URL}/blogs/{blog_handle}/{post_handle}",
                 lastmod=post.get("published_at"), changefreq="monthly", priority="0.5")

    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration + tostring(urlset, encoding="unicode")
