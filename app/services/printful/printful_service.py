import logging
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)


class PrintfulService:
    """Service for integrating with Printful API to get product costs"""

    def __init__(self):
        self.api_key = settings.PRINTFUL_API_KEY
        self.base_url = "https://api.printful.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def calculate_total_cost(self, shopify_product_id: str) -> Optional[float]:
        """
        Calculate total cost for a product including printing and shipping
        """
        try:
            # Get product details from Printful
            product_data = self._get_product_data(shopify_product_id)
            if not product_data:
                logger.warning(f"No Printful data found for product {shopify_product_id}")
                return None

            # Calculate costs
            base_cost = product_data.get("base_cost", 0)
            printing_cost = self._calculate_printing_cost(product_data)
            shipping_cost = self._calculate_shipping_cost(product_data)

            total_cost = base_cost + printing_cost + shipping_cost

            logger.info(f"Calculated cost for product {shopify_product_id}: ${total_cost:.2f}")
            return total_cost

        except Exception as e:
            logger.error(f"Error calculating cost for product {shopify_product_id}: {str(e)}")
            return None

    def _get_product_data(self, shopify_product_id: str) -> Optional[Dict[str, Any]]:
        """
        Get product data from Printful API
        """
        try:
            # In a real implementation, this would map Shopify product ID to Printful product
            # For now, return mock data based on product type
            if "shirt" in shopify_product_id.lower():
                return {
                    "base_cost": 8.50,
                    "print_type": "screen_print",
                    "shipping_cost": 3.99
                }
            elif "shorts" in shopify_product_id.lower():
                return {
                    "base_cost": 12.00,
                    "print_type": "dtg",
                    "shipping_cost": 4.50
                }
            elif "jacket" in shopify_product_id.lower():
                return {
                    "base_cost": 18.00,
                    "print_type": "embroidery",
                    "shipping_cost": 6.99
                }
            else:
                return {
                    "base_cost": 10.00,
                    "print_type": "screen_print",
                    "shipping_cost": 4.25
                }

        except Exception as e:
            logger.error(f"Error getting product data: {str(e)}")
            return None

    def _calculate_printing_cost(self, product_data: Dict[str, Any]) -> float:
        """
        Calculate printing cost based on print type and complexity
        """
        print_type = product_data.get("print_type", "screen_print")

        # Cost per print based on type
        print_costs = {
            "screen_print": 2.50,
            "dtg": 4.00,
            "embroidery": 3.75,
            "heat_transfer": 3.25
        }

        return print_costs.get(print_type, 3.00)

    def _calculate_shipping_cost(self, product_data: Dict[str, Any]) -> float:
        """
        Calculate shipping cost
        """
        return product_data.get("shipping_cost", 4.00)

    def get_product_variants(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Get product variants and their costs
        """
        try:
            # Mock implementation - in real app would call Printful API
            return {
                "variants": [
                    {"id": "small", "cost": 15.50},
                    {"id": "medium", "cost": 15.50},
                    {"id": "large", "cost": 15.50},
                    {"id": "xl", "cost": 16.00}
                ]
            }
        except Exception as e:
            logger.error(f"Error getting variants for product {product_id}: {str(e)}")
            return None

    def update_costs_from_printful(self, products: list) -> Dict[str, Any]:
        """
        Update costs for multiple products from Printful
        """
        results = {
            "updated": 0,
            "errors": 0,
            "total": len(products)
        }

        for product in products:
            try:
                cost = self.calculate_total_cost(str(product.shopify_id))
                if cost and cost != product.cost_price:
                    old_cost = product.cost_price
                    product.cost_price = cost
                    product.gross_margin = product.price - cost if product.price else 0
                    results["updated"] += 1
                    logger.info(f"Updated cost for {product.title}: ${old_cost:.2f} -> ${cost:.2f}")
                elif cost:
                    logger.debug(f"Cost unchanged for {product.title}: ${cost:.2f}")
            except Exception as e:
                results["errors"] += 1
                logger.error(f"Error updating cost for {product.title}: {str(e)}")

        return results


# Global instance
printful_service = PrintfulService()