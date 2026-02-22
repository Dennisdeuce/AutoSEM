"""
Checkout Audit Service
Analyzes abandoned checkouts and order funnel to diagnose conversion problems.

Key question: 509 ad clicks, 0 purchases — where are visitors dropping off?
- Never reaching product pages?
- Adding to cart but abandoning checkout?
- Starting checkout but not completing payment?
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("autosem.checkout_audit")


class CheckoutAuditor:
    """Analyzes Shopify abandoned checkouts and orders."""

    def __init__(self, shopify_api_func):
        """
        Args:
            shopify_api_func: The _api(method, endpoint, **kwargs) function
                              from shopify.py for making authenticated requests.
        """
        self._api = shopify_api_func

    def get_abandoned_checkouts(self, limit: int = 250) -> Dict:
        """Fetch abandoned checkouts from Shopify.

        Shopify keeps abandoned checkouts for 3 months.
        """
        data = self._api("GET", f"checkouts.json?limit={limit}")
        checkouts = data.get("checkouts", [])
        return {
            "count": len(checkouts),
            "checkouts": checkouts,
        }

    def get_recent_orders(self, limit: int = 50, status: str = "any") -> Dict:
        """Fetch recent orders for funnel analysis."""
        data = self._api(
            "GET",
            f"orders.json?status={status}&limit={limit}"
            f"&fields=id,order_number,name,total_price,created_at,"
            f"landing_site,referring_site,source_name,customer,"
            f"line_items,financial_status,cancelled_at,discount_codes",
        )
        orders = data.get("orders", [])
        return {
            "count": len(orders),
            "orders": orders,
        }

    def analyze_abandonment(self, checkouts: List[Dict]) -> Dict:
        """Analyze each abandoned checkout for actionable insights."""
        product_counts = Counter()
        step_counts = {"contact_info": 0, "shipping": 0, "payment": 0, "unknown": 0}
        utm_counts = {"meta": 0, "tiktok": 0, "google": 0, "organic": 0, "direct": 0, "other": 0}
        total_value = 0.0
        analyzed = []

        for co in checkouts:
            cart_value = float(co.get("total_price", 0) or 0)
            total_value += cart_value
            line_items = co.get("line_items", []) or []

            # Products in cart
            products = []
            for item in line_items:
                title = item.get("title", "Unknown")
                product_counts[title] += 1
                products.append({
                    "title": title,
                    "variant_title": item.get("variant_title", ""),
                    "quantity": item.get("quantity", 1),
                    "price": item.get("price", "0.00"),
                    "product_id": item.get("product_id"),
                })

            # Determine checkout step reached
            step = self._determine_step(co)
            step_counts[step] += 1

            # UTM attribution
            landing = co.get("landing_site", "") or ""
            referring = co.get("referring_site", "") or ""
            source = self._classify_source(landing, referring)
            utm_counts[source] += 1

            # Extract UTM params
            utm_params = self._extract_utm(landing)

            analyzed.append({
                "checkout_id": co.get("id"),
                "created_at": co.get("created_at"),
                "cart_value": cart_value,
                "currency": co.get("currency", "USD"),
                "products": products,
                "step_reached": step,
                "email": co.get("email", ""),
                "landing_site": landing[:200] if landing else "",
                "referring_site": referring[:200] if referring else "",
                "source": source,
                "utm": utm_params,
                "recovery_url": co.get("abandoned_checkout_url", ""),
            })

        most_abandoned = [
            {"product": title, "abandoned_count": count}
            for title, count in product_counts.most_common(10)
        ]

        return {
            "total_abandoned": len(checkouts),
            "total_abandoned_value": round(total_value, 2),
            "most_abandoned_products": most_abandoned,
            "abandonment_by_step": step_counts,
            "utm_attribution": utm_counts,
            "checkouts": analyzed,
        }

    def generate_report(self, days_back: int = 30) -> Dict:
        """Generate a full checkout audit report."""

        # Fetch data
        checkout_data = self.get_abandoned_checkouts(limit=250)
        order_data = self.get_recent_orders(limit=50)

        all_checkouts = checkout_data["checkouts"]
        all_orders = order_data["orders"]

        # Filter by time windows
        now = datetime.now(timezone.utc)
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=days_back)

        checkouts_7d = []
        checkouts_30d = []
        for co in all_checkouts:
            created = co.get("created_at", "")
            if not created:
                continue
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if dt >= cutoff_7d:
                checkouts_7d.append(co)
            if dt >= cutoff_30d:
                checkouts_30d.append(co)

        # Analyze
        analysis_7d = self.analyze_abandonment(checkouts_7d)
        analysis_30d = self.analyze_abandonment(checkouts_30d)

        # Order stats
        completed = [o for o in all_orders if not o.get("cancelled_at")]
        total_revenue = sum(float(o.get("total_price", 0) or 0) for o in completed)
        aov = total_revenue / len(completed) if completed else 0

        # Recommendations
        recommendations = self._generate_recommendations(
            analysis_30d, len(completed), total_revenue,
        )

        return {
            "status": "ok",
            "generated_at": now.isoformat(),
            "abandoned_checkouts_7d": analysis_7d["total_abandoned"],
            "abandoned_checkouts_30d": analysis_30d["total_abandoned"],
            "abandoned_cart_value_7d": f"${analysis_7d['total_abandoned_value']:.2f}",
            "abandoned_cart_value_30d": f"${analysis_30d['total_abandoned_value']:.2f}",
            "most_abandoned_products": analysis_30d["most_abandoned_products"],
            "abandonment_by_step": analysis_30d["abandonment_by_step"],
            "utm_attribution": analysis_30d["utm_attribution"],
            "recent_orders": {
                "count": len(completed),
                "total_count_all_status": len(all_orders),
                "revenue": f"${total_revenue:.2f}",
                "aov": f"${aov:.2f}",
            },
            "recommendations": recommendations,
            "detail_7d": {
                "checkouts": analysis_7d["checkouts"][:20],
            },
        }

    def get_recoverable_carts(self, hours_back: int = 48) -> Dict:
        """Get abandoned checkouts from last N hours with recovery URLs.

        Returns carts that have:
        - A customer email (for sending recovery email)
        - A recovery URL (Shopify-generated checkout recovery link)
        - Items still in the cart
        """
        checkout_data = self.get_abandoned_checkouts(limit=250)
        all_checkouts = checkout_data["checkouts"]

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        recoverable = []
        for co in all_checkouts:
            created = co.get("created_at", "")
            if not created:
                continue
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if dt < cutoff:
                continue

            email = co.get("email", "")
            recovery_url = co.get("abandoned_checkout_url", "")
            line_items = co.get("line_items", []) or []

            if not email or not line_items:
                continue

            cart_value = float(co.get("total_price", 0) or 0)
            customer = co.get("customer", {}) or {}

            products = [
                {
                    "title": item.get("title", ""),
                    "quantity": item.get("quantity", 1),
                    "price": item.get("price", "0.00"),
                }
                for item in line_items
            ]

            recoverable.append({
                "checkout_id": co.get("id"),
                "created_at": created,
                "email": email,
                "first_name": customer.get("first_name", ""),
                "last_name": customer.get("last_name", ""),
                "cart_value": cart_value,
                "currency": co.get("currency", "USD"),
                "products": products,
                "recovery_url": recovery_url,
                "landing_site": (co.get("landing_site") or "")[:200],
            })

        total_recoverable_value = sum(c["cart_value"] for c in recoverable)

        return {
            "status": "ok",
            "hours_back": hours_back,
            "recoverable_count": len(recoverable),
            "recoverable_value": f"${total_recoverable_value:.2f}",
            "carts": recoverable,
        }

    # ─── Private Helpers ─────────────────────────────────────────

    @staticmethod
    def _determine_step(checkout: Dict) -> str:
        """Determine which checkout step was reached.

        Shopify doesn't expose step directly, so we infer from filled fields.
        """
        has_email = bool(checkout.get("email"))
        has_shipping = bool(checkout.get("shipping_address"))
        billing = checkout.get("billing_address")
        has_billing = bool(billing and billing.get("address1"))

        if has_billing or has_shipping:
            # Got to payment step or beyond
            if checkout.get("gateway") or checkout.get("payment_url"):
                return "payment"
            return "shipping"
        elif has_email:
            return "contact_info"
        return "unknown"

    @staticmethod
    def _classify_source(landing_site: str, referring_site: str) -> str:
        """Classify the traffic source from landing/referring URLs."""
        combined = (landing_site + " " + referring_site).lower()

        if "utm_source=meta" in combined or "utm_source=facebook" in combined or "fbclid" in combined:
            return "meta"
        if "utm_source=tiktok" in combined or "ttclid" in combined:
            return "tiktok"
        if "utm_source=google" in combined or "gclid" in combined:
            return "google"
        if referring_site:
            ref_lower = referring_site.lower()
            if "facebook.com" in ref_lower or "instagram.com" in ref_lower:
                return "meta"
            if "tiktok.com" in ref_lower:
                return "tiktok"
            if "google" in ref_lower:
                return "google"
            return "organic"
        return "direct"

    @staticmethod
    def _extract_utm(url: str) -> Dict:
        """Extract UTM parameters from a URL."""
        if not url or "?" not in url:
            return {}
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            return {
                k: v[0] for k, v in params.items()
                if k.startswith("utm_") or k in ("fbclid", "gclid", "ttclid")
            }
        except Exception:
            return {}

    @staticmethod
    def _generate_recommendations(analysis: Dict, order_count: int, revenue: float) -> List[str]:
        """Generate actionable recommendations from the analysis."""
        recs = []
        total = analysis.get("total_abandoned", 0)
        steps = analysis.get("abandonment_by_step", {})
        utm = analysis.get("utm_attribution", {})
        value = analysis.get("total_abandoned_value", 0)

        if total == 0 and order_count == 0:
            recs.append("CRITICAL: Zero abandoned checkouts AND zero orders — visitors are NOT adding to cart. "
                         "Focus on product page CRO: reviews, trust signals, compelling CTAs.")
            return recs

        if total == 0 and order_count > 0:
            recs.append("No abandoned checkouts found — checkout completion rate appears healthy.")
            return recs

        if total > 0:
            recs.append(f"Found {total} abandoned checkouts worth ${value:.2f} in the last 30 days.")

        # Step analysis
        contact = steps.get("contact_info", 0)
        shipping = steps.get("shipping", 0)
        payment = steps.get("payment", 0)
        unknown = steps.get("unknown", 0)

        if unknown > total * 0.5:
            recs.append(f"HIGH: {unknown}/{total} abandoned before entering email — "
                         "product pages or cart experience is losing visitors. "
                         "Add trust signals, reviews, and urgency elements.")

        if contact > total * 0.3:
            recs.append(f"MEDIUM: {contact}/{total} abandoned at contact info step — "
                         "consider guest checkout, simpler forms, or email-only first step.")

        if shipping > total * 0.2:
            recs.append(f"MEDIUM: {shipping}/{total} abandoned at shipping step — "
                         "shipping cost surprise? Show free shipping earlier. "
                         "Consider showing estimated delivery time.")

        if payment > total * 0.1:
            recs.append(f"LOW: {payment}/{total} abandoned at payment step — "
                         "add more payment options (Apple Pay, Google Pay, Shop Pay). "
                         "Ensure SSL trust badges are visible.")

        # UTM analysis
        meta_count = utm.get("meta", 0)
        if meta_count > 0:
            recs.append(f"Meta ads drove {meta_count} abandoned checkouts — "
                         "visitors ARE reaching the store from ads but not converting. "
                         "This confirms the ad targeting is working, focus on CRO.")

        # Recovery
        if total > 3:
            recs.append(f"ACTION: Enable abandoned cart recovery emails via Klaviyo. "
                         f"Use GET /shopify/cart-recovery to get recovery URLs for the last 48h.")

        # Value
        if value > 100:
            recs.append(f"REVENUE OPPORTUNITY: ${value:.2f} in abandoned carts. "
                         "With a 10-15% recovery rate, that's ${:.2f} recoverable.".format(value * 0.125))

        return recs
