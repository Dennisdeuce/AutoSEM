import shopify
from typing import List, Dict, Any
from app.core.config import settings
from app.schemas.product import ProductCreate


class ShopifyService:
    def __init__(self):
        shopify.ShopifyResource.set_site(f"https://{settings.SHOPIFY_SHOP_DOMAIN}/admin/api/{settings.SHOPIFY_API_VERSION}")
        shopify.ShopifyResource.set_headers({"X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN})

    def get_products(self) -> List[Dict[str, Any]]:
        """Fetch all products from Shopify"""
        products = shopify.Product.find()
        return [product.to_dict() for product in products]

    def get_product(self, product_id: str) -> Dict[str, Any]:
        """Fetch a specific product from Shopify"""
        product = shopify.Product.find(product_id)
        return product.to_dict()

    def get_orders(self, **kwargs) -> List[Dict[str, Any]]:
        """Fetch orders from Shopify"""
        orders = shopify.Order.find(**kwargs)
        return [order.to_dict() for order in orders]

    def create_webhook(self, topic: str, address: str) -> Dict[str, Any]:
        """Create a webhook for real-time updates"""
        webhook = shopify.Webhook.create({
            "topic": topic,
            "address": address,
            "format": "json"
        })
        return webhook.to_dict()

    def transform_product_to_schema(self, shopify_product: Dict[str, Any]) -> ProductCreate:
        """Transform Shopify product data to our ProductCreate schema"""
        return ProductCreate(
            shopify_id=str(shopify_product["id"]),
            title=shopify_product["title"],
            description=shopify_product.get("body_html"),
            handle=shopify_product.get("handle"),
            product_type=shopify_product.get("product_type"),
            vendor=shopify_product.get("vendor"),
            price=float(shopify_product["variants"][0]["price"]) if shopify_product.get("variants") else None,
            compare_at_price=float(shopify_product["variants"][0]["compare_at_price"]) if shopify_product.get("variants") and shopify_product["variants"][0].get("compare_at_price") else None,
            inventory_quantity=shopify_product["variants"][0]["inventory_quantity"] if shopify_product.get("variants") else 0,
            images=",".join([img["src"] for img in shopify_product.get("images", [])]),
            variants=str(shopify_product.get("variants", [])),
            tags=",".join(shopify_product.get("tags", []))
        )


shopify_service = ShopifyService()