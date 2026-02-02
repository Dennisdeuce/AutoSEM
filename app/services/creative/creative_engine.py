from typing import List, Dict, Any
from app.models import Product


class CreativeEngine:
    def generate_ad_content(self, product: Product) -> Dict[str, Any]:
        return {
            "headlines": self.generate_headlines(product),
            "descriptions": self.generate_descriptions(product),
            "images": self.process_images(product.images),
            "videos": self.generate_video(product),
        }

    def generate_headlines(self, product: Product) -> List[str]:
        templates = [
            f"{product.title} - Free Shipping",
            f"Shop {product.product_type} | Court Sportswear",
            f"Tennis {product.product_type} for USTA Players",
            f"{product.title} - Starting at ${product.price}",
            f"Premium Tennis Apparel | {product.title}",
            f"Custom {product.product_type} | {product.vendor}",
            f"USTA Approved {product.title}",
            f"Professional Tennis {product.product_type}",
            f"{product.title} - Best Seller",
            f"Tennis Team {product.product_type}",
            f"High-Quality {product.title}",
            f"{product.vendor} {product.product_type}",
            f"Comfortable {product.title}",
            f"Durable Tennis {product.product_type}",
            f"{product.title} - Limited Stock"
        ]
        return templates[:15]

    def generate_descriptions(self, product: Product) -> List[str]:
        descriptions = [
            f"Premium {product.product_type} designed for serious tennis players. Made by {product.vendor}.",
            f"High-quality tennis apparel for USTA tournaments and league play. Free shipping on orders over $50.",
            f"Professional-grade {product.product_type} with moisture-wicking fabric. Perfect for competitive tennis.",
            f"Custom tennis gear for teams and individuals. Durable construction that lasts.",
            f"Designed for comfort and performance on the court. Trusted by tennis professionals worldwide."
        ]
        return descriptions

    def process_images(self, images_str: str) -> List[str]:
        """Process and optimize images for ads"""
        if not images_str:
            return []

        images = images_str.split(",")
        # In a real implementation, this would resize, crop, and optimize images
        # For now, just return the original URLs
        return images

    def generate_video(self, product: Product) -> str:
        """Generate video content for ads"""
        # Placeholder for video generation
        # Could use AI video generation or template-based creation
        return f"video_url_for_{product.id}"


creative_engine = CreativeEngine()