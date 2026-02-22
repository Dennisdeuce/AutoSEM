"""Conversion Funnel Audit Endpoint

Diagnoses the entire path from ad click to purchase.
Identifies blockers causing 0% conversion rate.
"""

import os
import re
import logging
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db, MetaTokenModel

logger = logging.getLogger("AutoSEM.ConversionAudit")
router = APIRouter()

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "4448da-3.myshopify.com")
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-10")
STORE_URL = "https://court-sportswear.com"


def _get_meta_token(db: Session) -> str:
    token_record = db.query(MetaTokenModel).first()
    if token_record and token_record.access_token:
        return token_record.access_token
    return os.environ.get("META_ACCESS_TOKEN", "")


def _appsecret_proof(token: str) -> str:
    import hashlib, hmac
    if not META_APP_SECRET:
        return ""
    return hmac.new(META_APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def _shopify_token() -> str:
    try:
        from app.routers.shopify import _get_token
        return _get_token()
    except Exception:
        return os.environ.get("SHOPIFY_ACCESS_TOKEN", "")


def _shopify_api(method: str, endpoint: str, **kwargs) -> dict:
    token = _shopify_token()
    if not token:
        return {"error": "No Shopify token"}
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    try:
        resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@router.get("/conversion-audit", summary="Full conversion funnel audit")
def conversion_audit(db: Session = Depends(get_db)):
    """Diagnose the entire conversion funnel from ad click to purchase.
    
    Checks: Meta Pixel, UTM params, landing page speed, Shopify checkouts,
    Klaviyo status, and generates prioritized recommendations.
    """
    audit = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "funnel": {},
        "pixel": {},
        "landing_page": {},
        "utm_tracking": {},
        "shopify": {},
        "klaviyo": {},
        "blockers": [],
        "recommendations": [],
    }

    # ── 1. Meta Pixel Check ──
    try:
        start = time.time()
        resp = requests.get(STORE_URL, timeout=10)
        load_ms = round((time.time() - start) * 1000)
        body = resp.text.lower()

        has_fbq = "fbq(" in body
        has_script = "connect.facebook.net" in body

        audit["pixel"]["fbq_present"] = has_fbq
        audit["pixel"]["fbevents_script"] = has_script
        audit["pixel"]["installed"] = has_fbq and has_script

        if not (has_fbq and has_script):
            audit["blockers"].append({
                "severity": "critical",
                "issue": "Meta Pixel is NOT installed on the store",
                "impact": "Meta cannot track ANY conversions — 0% attribution",
                "fix": "POST /api/v1/pixel/install",
            })

        audit["landing_page"]["url"] = STORE_URL
        audit["landing_page"]["load_time_ms"] = load_ms
        audit["landing_page"]["status_code"] = resp.status_code
        if load_ms > 3000:
            audit["blockers"].append({
                "severity": "high",
                "issue": f"Landing page loads in {load_ms}ms (target: < 3000ms)",
                "impact": "Mobile users bounce on slow pages",
                "fix": "Optimize images, reduce app scripts",
            })
    except Exception as e:
        audit["pixel"]["error"] = str(e)

    # ── 2. Meta Campaign & UTM Analysis ──
    meta_token = _get_meta_token(db)
    if meta_token and META_AD_ACCOUNT_ID:
        try:
            # Get campaigns
            camps = requests.get(
                f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/campaigns",
                params={
                    "fields": "id,name,status,objective,daily_budget",
                    "access_token": meta_token,
                    "appsecret_proof": _appsecret_proof(meta_token),
                    "limit": 50,
                },
                timeout=15,
            ).json().get("data", [])

            active_camps = [c for c in camps if c.get("status") == "ACTIVE"]
            audit["funnel"]["active_campaigns"] = len(active_camps)
            audit["funnel"]["total_campaigns"] = len(camps)

            # Check objectives
            for c in active_camps:
                obj = c.get("objective", "")
                if obj in ("LINK_CLICKS", "POST_ENGAGEMENT"):
                    audit["blockers"].append({
                        "severity": "high",
                        "issue": f"Campaign '{c.get('name')}' uses {obj} objective",
                        "impact": "Optimizes for clicks, NOT purchases. Low conversion rate.",
                        "fix": "Create new campaign with OUTCOME_SALES objective (requires pixel)",
                    })

            # Get ad URLs for UTM check
            ads_with_utms = 0
            ads_without_utms = 0
            for camp in active_camps:
                try:
                    adsets = requests.get(
                        f"{META_GRAPH_BASE}/{camp['id']}/adsets",
                        params={"fields": "id", "access_token": meta_token,
                                "appsecret_proof": _appsecret_proof(meta_token)},
                        timeout=10,
                    ).json().get("data", [])
                    for adset in adsets:
                        ads = requests.get(
                            f"{META_GRAPH_BASE}/{adset['id']}/ads",
                            params={
                                "fields": "id,name,creative{object_story_spec}",
                                "access_token": meta_token,
                                "appsecret_proof": _appsecret_proof(meta_token),
                            },
                            timeout=10,
                        ).json().get("data", [])
                        for ad in ads:
                            creative = ad.get("creative", {})
                            story = creative.get("object_story_spec", {})
                            link_data = story.get("link_data", {})
                            link_url = link_data.get("link", "")
                            if "utm_source" in link_url:
                                ads_with_utms += 1
                            else:
                                ads_without_utms += 1
                except Exception:
                    pass

            audit["utm_tracking"] = {
                "ads_with_utms": ads_with_utms,
                "ads_without_utms": ads_without_utms,
                "coverage": f"{ads_with_utms}/{ads_with_utms + ads_without_utms}" if (ads_with_utms + ads_without_utms) > 0 else "N/A",
            }
            if ads_without_utms > 0:
                audit["blockers"].append({
                    "severity": "medium",
                    "issue": f"{ads_without_utms} ad(s) missing UTM parameters",
                    "impact": "Cannot attribute Shopify orders back to specific campaigns",
                    "fix": "Add utm_source=meta&utm_medium=paid&utm_campaign={id} to ad URLs",
                })

            # Get performance metrics
            try:
                insights = requests.get(
                    f"{META_GRAPH_BASE}/act_{META_AD_ACCOUNT_ID}/insights",
                    params={
                        "fields": "impressions,clicks,spend,actions,cost_per_action_type",
                        "date_preset": "last_30d",
                        "access_token": meta_token,
                        "appsecret_proof": _appsecret_proof(meta_token),
                    },
                    timeout=15,
                ).json().get("data", [{}])[0]

                ad_clicks = int(insights.get("clicks", 0))
                ad_spend = float(insights.get("spend", 0))
                purchases = 0
                for action in insights.get("actions", []):
                    if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                        purchases = int(action.get("value", 0))

                audit["funnel"]["ad_impressions"] = int(insights.get("impressions", 0))
                audit["funnel"]["ad_clicks"] = ad_clicks
                audit["funnel"]["ad_spend"] = ad_spend
                audit["funnel"]["tracked_purchases"] = purchases
                audit["funnel"]["cpc"] = round(ad_spend / ad_clicks, 2) if ad_clicks else 0
            except Exception:
                pass

        except Exception as e:
            audit["funnel"]["meta_error"] = str(e)

    # ── 3. Shopify Checkout Data ──
    try:
        orders = _shopify_api("GET", "orders.json?status=any&limit=50")
        order_list = orders.get("orders", [])
        total_revenue = sum(float(o.get("total_price", 0)) for o in order_list)

        audit["shopify"]["recent_orders"] = len(order_list)
        audit["shopify"]["total_revenue"] = round(total_revenue, 2)
        audit["shopify"]["aov"] = round(total_revenue / len(order_list), 2) if order_list else 0

        # Check for abandoned checkouts
        checkouts = _shopify_api("GET", "checkouts.json?limit=250")
        checkout_list = checkouts.get("checkouts", [])
        audit["shopify"]["abandoned_checkouts"] = len(checkout_list)
        if checkout_list:
            abandoned_value = sum(float(c.get("total_price", 0) or 0) for c in checkout_list)
            audit["shopify"]["abandoned_cart_value"] = round(abandoned_value, 2)
    except Exception as e:
        audit["shopify"]["error"] = str(e)

    # ── 4. Klaviyo Status ──
    try:
        from app.routers.shopify import _api as shopify_internal_api
        # Check Klaviyo via internal API call
        klaviyo_resp = requests.get("https://auto-sem.replit.app/api/v1/klaviyo/status", timeout=5)
        klaviyo_data = klaviyo_resp.json()
        audit["klaviyo"] = {
            "connected": klaviyo_data.get("connected", False),
            "status": klaviyo_data.get("status", "unknown"),
            "message": klaviyo_data.get("message", ""),
        }
        if not klaviyo_data.get("connected"):
            audit["blockers"].append({
                "severity": "high",
                "issue": "Klaviyo API key is invalid",
                "impact": "Abandoned cart emails NOT sending. Losing recoverable revenue.",
                "fix": "POST /api/v1/klaviyo/validate-key with valid API key",
            })
    except Exception as e:
        audit["klaviyo"] = {"error": str(e)}

    # ── 5. Generate Recommendations ──
    recommendations = []
    blockers_by_severity = sorted(audit["blockers"], key=lambda b: 
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(b["severity"], 4))

    for b in blockers_by_severity:
        recommendations.append(f"[{b['severity'].upper()}] {b['issue']} → {b['fix']}")

    if not audit.get("pixel", {}).get("installed"):
        recommendations.insert(0, "PRIORITY 1: Install Meta Pixel (POST /api/v1/pixel/install)")
    
    recommendations.append("Add product reviews (0 reviews = low trust for new visitors)")
    recommendations.append("Add email popup for 10% discount (capture visitor emails)")
    recommendations.append("Consider retargeting campaign for cart abandoners")

    audit["recommendations"] = recommendations
    audit["overall_status"] = "critical" if any(b["severity"] == "critical" for b in audit["blockers"]) else (
        "warning" if audit["blockers"] else "healthy"
    )

    return audit
