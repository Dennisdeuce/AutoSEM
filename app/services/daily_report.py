"""
Daily Performance Report Service
Generates and sends automated daily performance reports via email.

Gathers metrics from Meta Ads, Shopify, and TikTok (if connected),
compares day-over-day and 7-day rolling averages, generates responsive
HTML email, and delivers via Klaviyo transactional API or SMTP fallback.
"""

import logging
import os
import smtplib
from datetime import datetime, date, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("autosem.daily_report")

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"
KLAVIYO_BASE_URL = "https://a.klaviyo.com/api"
KLAVIYO_REVISION = "2024-10-15"


class DailyReportService:
    """Generates and sends daily performance reports."""

    def __init__(self, db_session):
        self.db = db_session

    # ─── Data Gathering ──────────────────────────────────────────

    def gather_metrics(self, report_date: Optional[date] = None) -> Dict:
        """Fetch yesterday's data from all platforms.

        Args:
            report_date: The date to report on (defaults to yesterday).

        Returns:
            Dict with meta, shopify, tiktok, and campaigns sections.
        """
        if report_date is None:
            report_date = date.today() - timedelta(days=1)

        date_str = report_date.isoformat()
        metrics = {
            "report_date": date_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "meta": self._fetch_meta_daily(date_str),
            "shopify": self._fetch_shopify_daily(report_date),
            "tiktok": self._fetch_tiktok_daily(date_str),
            "campaigns": self._fetch_campaign_breakdown(date_str),
        }
        return metrics

    def compare_metrics(self, metrics: Dict) -> Dict:
        """Compare today's metrics with previous day and 7-day rolling average.

        Uses PerformanceSnapshotModel for historical data.
        """
        report_date = date.fromisoformat(metrics["report_date"])
        prev_date = report_date - timedelta(days=1)
        week_start = report_date - timedelta(days=7)

        # Get historical snapshots
        from app.database import PerformanceSnapshotModel
        from sqlalchemy import func

        # Previous day totals
        prev_row = self.db.query(
            func.sum(PerformanceSnapshotModel.spend).label("spend"),
            func.sum(PerformanceSnapshotModel.clicks).label("clicks"),
            func.sum(PerformanceSnapshotModel.impressions).label("impressions"),
            func.sum(PerformanceSnapshotModel.conversions).label("conversions"),
            func.sum(PerformanceSnapshotModel.revenue).label("revenue"),
        ).filter(
            PerformanceSnapshotModel.date == prev_date
        ).first()

        prev = {
            "spend": float(prev_row.spend or 0) if prev_row else 0,
            "clicks": int(prev_row.clicks or 0) if prev_row else 0,
            "impressions": int(prev_row.impressions or 0) if prev_row else 0,
            "conversions": int(prev_row.conversions or 0) if prev_row else 0,
            "revenue": float(prev_row.revenue or 0) if prev_row else 0,
        }

        # 7-day rolling average
        avg_row = self.db.query(
            func.avg(PerformanceSnapshotModel.spend).label("spend"),
            func.avg(PerformanceSnapshotModel.clicks).label("clicks"),
            func.avg(PerformanceSnapshotModel.impressions).label("impressions"),
            func.avg(PerformanceSnapshotModel.conversions).label("conversions"),
            func.avg(PerformanceSnapshotModel.revenue).label("revenue"),
        ).filter(
            PerformanceSnapshotModel.date >= week_start,
            PerformanceSnapshotModel.date < report_date,
        ).first()

        avg_7d = {
            "spend": round(float(avg_row.spend or 0), 2) if avg_row else 0,
            "clicks": round(float(avg_row.clicks or 0), 1) if avg_row else 0,
            "impressions": round(float(avg_row.impressions or 0), 1) if avg_row else 0,
            "conversions": round(float(avg_row.conversions or 0), 1) if avg_row else 0,
            "revenue": round(float(avg_row.revenue or 0), 2) if avg_row else 0,
        }

        # Current day totals from gathered metrics
        meta = metrics.get("meta", {})
        current = {
            "spend": meta.get("spend", 0),
            "clicks": meta.get("clicks", 0),
            "impressions": meta.get("impressions", 0),
            "conversions": meta.get("conversions", 0),
            "revenue": metrics.get("shopify", {}).get("revenue", 0),
        }

        def _change(curr, prev_val):
            if prev_val == 0:
                return None
            return round(((curr - prev_val) / prev_val) * 100, 1)

        def _vs_avg(curr, avg_val):
            if avg_val == 0:
                return None
            return round(((curr - avg_val) / avg_val) * 100, 1)

        return {
            "current": current,
            "previous_day": prev,
            "avg_7d": avg_7d,
            "day_over_day": {
                "spend": _change(current["spend"], prev["spend"]),
                "clicks": _change(current["clicks"], prev["clicks"]),
                "impressions": _change(current["impressions"], prev["impressions"]),
                "conversions": _change(current["conversions"], prev["conversions"]),
                "revenue": _change(current["revenue"], prev["revenue"]),
            },
            "vs_7d_avg": {
                "spend": _vs_avg(current["spend"], avg_7d["spend"]),
                "clicks": _vs_avg(current["clicks"], avg_7d["clicks"]),
                "impressions": _vs_avg(current["impressions"], avg_7d["impressions"]),
                "conversions": _vs_avg(current["conversions"], avg_7d["conversions"]),
                "revenue": _vs_avg(current["revenue"], avg_7d["revenue"]),
            },
        }

    def generate_report(self, report_date: Optional[date] = None) -> Dict:
        """Generate a full report with metrics, comparisons, and HTML."""
        metrics = self.gather_metrics(report_date)
        comparison = self.compare_metrics(metrics)
        recommendations = self._generate_recommendations(metrics, comparison)
        html = self.generate_html(metrics, comparison, recommendations)

        return {
            "status": "ok",
            "report_date": metrics["report_date"],
            "generated_at": metrics["generated_at"],
            "metrics": metrics,
            "comparison": comparison,
            "recommendations": recommendations,
            "html": html,
        }

    def send_report(self, report: Dict, recipient: Optional[str] = None) -> Dict:
        """Send the report email via Klaviyo transactional API or SMTP fallback.

        Args:
            report: Full report dict from generate_report().
            recipient: Override email address (defaults to REPORT_RECIPIENT env var).
        """
        to_email = recipient or os.environ.get("REPORT_RECIPIENT", "")
        if not to_email:
            return {"status": "error", "message": "No recipient configured. Set REPORT_RECIPIENT env var."}

        subject = f"AutoSEM Daily Report — {report['report_date']}"
        html_body = report.get("html", "")

        # Try Klaviyo transactional first
        klaviyo_result = self._send_via_klaviyo(to_email, subject, html_body)
        if klaviyo_result.get("success"):
            return {"status": "sent", "method": "klaviyo", "to": to_email}

        # Fallback to SMTP
        smtp_result = self._send_via_smtp(to_email, subject, html_body)
        if smtp_result.get("success"):
            return {"status": "sent", "method": "smtp", "to": to_email}

        return {
            "status": "error",
            "message": "Both Klaviyo and SMTP delivery failed",
            "klaviyo_error": klaviyo_result.get("error"),
            "smtp_error": smtp_result.get("error"),
        }

    # ─── HTML Generation ──────────────────────────────────────────

    def generate_html(self, metrics: Dict, comparison: Dict,
                      recommendations: List[str]) -> str:
        """Generate responsive HTML email with metric grid and trend arrows."""
        report_date = metrics.get("report_date", "")
        meta = metrics.get("meta", {})
        shopify = metrics.get("shopify", {})
        tiktok = metrics.get("tiktok", {})
        campaigns = metrics.get("campaigns", [])
        dod = comparison.get("day_over_day", {})

        def arrow(val):
            if val is None:
                return '<span style="color:#888">—</span>'
            if val > 0:
                return f'<span style="color:#22c55e">+{val}%</span>'
            if val < 0:
                return f'<span style="color:#ef4444">{val}%</span>'
            return '<span style="color:#888">0%</span>'

        # For spend, down is good (green) and up is bad (red)
        def arrow_inverse(val):
            if val is None:
                return '<span style="color:#888">—</span>'
            if val > 0:
                return f'<span style="color:#ef4444">+{val}%</span>'
            if val < 0:
                return f'<span style="color:#22c55e">{val}%</span>'
            return '<span style="color:#888">0%</span>'

        spend = meta.get("spend", 0)
        clicks = meta.get("clicks", 0)
        impressions = meta.get("impressions", 0)
        ctr = round((clicks / impressions * 100) if impressions > 0 else 0, 2)
        cpc = round((spend / clicks) if clicks > 0 else 0, 2)
        orders = shopify.get("orders", 0)
        revenue = shopify.get("revenue", 0)
        roas = round((revenue / spend) if spend > 0 else 0, 2)

        # Campaign rows
        campaign_rows = ""
        for c in campaigns[:10]:
            c_spend = c.get("spend", 0)
            c_clicks = c.get("clicks", 0)
            c_ctr = round((c_clicks / c.get("impressions", 1)) * 100, 2) if c.get("impressions", 0) > 0 else 0
            c_cpc = round((c_spend / c_clicks), 2) if c_clicks > 0 else 0
            status_color = "#22c55e" if c.get("status", "").upper() == "ACTIVE" else "#f59e0b"
            campaign_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">
                {c.get('name', 'Unknown')[:40]}
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center">
                <span style="color:{status_color};font-weight:600;font-size:12px">
                  {c.get('status', '?').upper()}
                </span>
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;font-size:14px">
                ${c_spend:.2f}
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;font-size:14px">
                {c_clicks}
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;font-size:14px">
                {c_ctr}%
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;font-size:14px">
                ${c_cpc:.2f}
              </td>
            </tr>"""

        if not campaign_rows:
            campaign_rows = """
            <tr>
              <td colspan="6" style="padding:16px;text-align:center;color:#888;font-size:14px">
                No campaign data available for this period
              </td>
            </tr>"""

        # Recommendations
        rec_items = ""
        for rec in recommendations:
            rec_items += f'<li style="padding:4px 0;font-size:14px;color:#374151">{rec}</li>'
        if not rec_items:
            rec_items = '<li style="padding:4px 0;font-size:14px;color:#888">No recommendations for today</li>'

        # TikTok section (only show if connected)
        tiktok_section = ""
        if tiktok.get("connected"):
            tt_spend = tiktok.get("spend", 0)
            tt_clicks = tiktok.get("clicks", 0)
            tiktok_section = f"""
            <div style="margin-top:16px;padding:12px;background:#f0f9ff;border-radius:8px;border:1px solid #bae6fd">
              <h3 style="margin:0 0 8px;font-size:14px;color:#0369a1">TikTok Ads</h3>
              <table style="width:100%">
                <tr>
                  <td style="font-size:13px;color:#555">Spend: <b>${tt_spend:.2f}</b></td>
                  <td style="font-size:13px;color:#555">Clicks: <b>{tt_clicks}</b></td>
                  <td style="font-size:13px;color:#555">Impressions: <b>{tiktok.get('impressions', 0)}</b></td>
                </tr>
              </table>
            </div>"""

        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1)">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1e40af,#7c3aed);padding:24px 32px">
            <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700">AutoSEM Daily Report</h1>
            <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:14px">
              {report_date} &middot; Court Sportswear
            </p>
          </td>
        </tr>

        <!-- KPI Grid -->
        <tr>
          <td style="padding:24px 32px 0">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">Ad Spend</div>
                    <div style="font-size:24px;font-weight:700;color:#1e293b;margin:4px 0">${spend:.2f}</div>
                    <div>{arrow_inverse(dod.get('spend'))}</div>
                  </div>
                </td>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">Clicks</div>
                    <div style="font-size:24px;font-weight:700;color:#1e293b;margin:4px 0">{clicks}</div>
                    <div>{arrow(dod.get('clicks'))}</div>
                  </div>
                </td>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">Revenue</div>
                    <div style="font-size:24px;font-weight:700;color:#1e293b;margin:4px 0">${revenue:.2f}</div>
                    <div>{arrow(dod.get('revenue'))}</div>
                  </div>
                </td>
              </tr>
              <tr>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">CTR</div>
                    <div style="font-size:24px;font-weight:700;color:#1e293b;margin:4px 0">{ctr}%</div>
                  </div>
                </td>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">CPC</div>
                    <div style="font-size:24px;font-weight:700;color:#1e293b;margin:4px 0">${cpc:.2f}</div>
                  </div>
                </td>
                <td width="33%" style="padding:8px">
                  <div style="background:#f8fafc;border-radius:8px;padding:16px;text-align:center;border:1px solid #e2e8f0">
                    <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">ROAS</div>
                    <div style="font-size:24px;font-weight:700;color:{'#22c55e' if roas >= 1.5 else '#ef4444' if roas < 1 else '#f59e0b'};margin:4px 0">{roas}x</div>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Shopify Summary -->
        <tr>
          <td style="padding:16px 32px 0">
            <div style="padding:12px 16px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0">
              <h3 style="margin:0 0 8px;font-size:14px;color:#166534">Shopify Store</h3>
              <table style="width:100%">
                <tr>
                  <td style="font-size:13px;color:#555">Orders: <b>{orders}</b></td>
                  <td style="font-size:13px;color:#555">Revenue: <b>${revenue:.2f}</b></td>
                  <td style="font-size:13px;color:#555">AOV: <b>${shopify.get('aov', 0):.2f}</b></td>
                </tr>
              </table>
            </div>
            {tiktok_section}
          </td>
        </tr>

        <!-- Campaign Breakdown -->
        <tr>
          <td style="padding:24px 32px 0">
            <h2 style="margin:0 0 12px;font-size:16px;color:#1e293b">Campaign Performance</h2>
            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
              <tr style="background:#f8fafc">
                <th style="padding:10px 12px;text-align:left;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">Campaign</th>
                <th style="padding:10px 12px;text-align:center;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">Status</th>
                <th style="padding:10px 12px;text-align:right;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">Spend</th>
                <th style="padding:10px 12px;text-align:right;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">Clicks</th>
                <th style="padding:10px 12px;text-align:right;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">CTR</th>
                <th style="padding:10px 12px;text-align:right;font-size:12px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5e7eb">CPC</th>
              </tr>
              {campaign_rows}
            </table>
          </td>
        </tr>

        <!-- Recommendations -->
        <tr>
          <td style="padding:24px 32px">
            <h2 style="margin:0 0 12px;font-size:16px;color:#1e293b">Recommendations</h2>
            <ul style="margin:0;padding-left:20px">
              {rec_items}
            </ul>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e5e7eb">
            <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center">
              AutoSEM &middot; Automated at 08:00 UTC daily &middot;
              <a href="https://auto-sem.replit.app/dashboard" style="color:#6366f1">View Dashboard</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
        return html

    # ─── Private: Platform Data Fetchers ──────────────────────────

    def _fetch_meta_daily(self, date_str: str) -> Dict:
        """Fetch Meta Ads data for a single day."""
        from app.database import MetaTokenModel

        token_record = self.db.query(MetaTokenModel).first()
        access_token = ""
        if token_record and token_record.access_token:
            access_token = token_record.access_token
        else:
            access_token = os.environ.get("META_ACCESS_TOKEN", "")

        ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
        if not access_token or not ad_account_id:
            return {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "connected": False}

        try:
            resp = requests.get(
                f"{META_GRAPH_BASE}/act_{ad_account_id}/insights",
                params={
                    "time_range": f'{{"since":"{date_str}","until":"{date_str}"}}',
                    "fields": "spend,impressions,clicks,actions",
                    "access_token": access_token,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                row = data[0]
                conversions = 0
                for action in row.get("actions", []):
                    if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                        conversions += int(action.get("value", 0))
                return {
                    "spend": float(row.get("spend", 0)),
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "conversions": conversions,
                    "connected": True,
                }
            return {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "connected": True}
        except Exception as e:
            logger.warning(f"Meta daily fetch failed: {e}")
            return {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "connected": False}

    def _fetch_shopify_daily(self, report_date: date) -> Dict:
        """Fetch Shopify orders for a single day."""
        try:
            from app.routers.shopify import _api
            start = f"{report_date.isoformat()}T00:00:00-00:00"
            end = f"{(report_date + timedelta(days=1)).isoformat()}T00:00:00-00:00"

            data = _api(
                "GET",
                f"orders.json?status=any&created_at_min={start}&created_at_max={end}"
                f"&fields=id,order_number,total_price,financial_status,cancelled_at",
            )
            orders = data.get("orders", [])
            completed = [o for o in orders if not o.get("cancelled_at")]
            revenue = sum(float(o.get("total_price", 0) or 0) for o in completed)
            aov = round(revenue / len(completed), 2) if completed else 0

            return {
                "orders": len(completed),
                "total_orders": len(orders),
                "revenue": round(revenue, 2),
                "aov": aov,
                "connected": True,
            }
        except Exception as e:
            logger.warning(f"Shopify daily fetch failed: {e}")
            return {"orders": 0, "revenue": 0, "aov": 0, "connected": False}

    def _fetch_tiktok_daily(self, date_str: str) -> Dict:
        """Fetch TikTok Ads data for a single day."""
        from app.database import TikTokTokenModel
        import json as _json

        token_record = self.db.query(TikTokTokenModel).first()
        if not token_record or not token_record.access_token:
            access_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
            advertiser_id = os.environ.get("TIKTOK_ADVERTISER_ID", "")
        else:
            access_token = token_record.access_token
            advertiser_id = token_record.advertiser_id or ""

        if not access_token or not advertiser_id:
            return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}

        try:
            headers = {"Access-Token": access_token, "Content-Type": "application/json"}
            resp = requests.get(
                f"{TIKTOK_API_BASE}/report/integrated/get/",
                headers=headers,
                params={
                    "advertiser_id": advertiser_id,
                    "report_type": "BASIC",
                    "dimensions": _json.dumps(["campaign_id"]),
                    "data_level": "AUCTION_CAMPAIGN",
                    "start_date": date_str,
                    "end_date": date_str,
                    "metrics": _json.dumps(["spend", "impressions", "clicks"]),
                },
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == 0:
                rows = result.get("data", {}).get("list", [])
                return {
                    "spend": sum(float(r.get("metrics", {}).get("spend", 0)) for r in rows),
                    "impressions": sum(int(r.get("metrics", {}).get("impressions", 0)) for r in rows),
                    "clicks": sum(int(r.get("metrics", {}).get("clicks", 0)) for r in rows),
                    "connected": True,
                }
            return {"spend": 0, "impressions": 0, "clicks": 0, "connected": True}
        except Exception as e:
            logger.warning(f"TikTok daily fetch failed: {e}")
            return {"spend": 0, "impressions": 0, "clicks": 0, "connected": False}

    def _fetch_campaign_breakdown(self, date_str: str) -> List[Dict]:
        """Get per-campaign performance from Meta for the given day."""
        from app.database import MetaTokenModel

        token_record = self.db.query(MetaTokenModel).first()
        access_token = ""
        if token_record and token_record.access_token:
            access_token = token_record.access_token
        else:
            access_token = os.environ.get("META_ACCESS_TOKEN", "")

        ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
        if not access_token or not ad_account_id:
            return []

        try:
            resp = requests.get(
                f"{META_GRAPH_BASE}/act_{ad_account_id}/campaigns",
                params={
                    "fields": (
                        f"id,name,status,"
                        f"insights.time_range({{\"since\":\"{date_str}\",\"until\":\"{date_str}\"}})"
                        f"{{spend,impressions,clicks,ctr,cpc}}"
                    ),
                    "access_token": access_token,
                    "limit": 50,
                },
                timeout=20,
            )
            resp.raise_for_status()
            campaigns = []
            for c in resp.json().get("data", []):
                insights = c.get("insights", {}).get("data", [{}])
                insight = insights[0] if insights else {}
                spend = float(insight.get("spend", 0))
                if spend > 0 or int(insight.get("impressions", 0)) > 0:
                    campaigns.append({
                        "name": c.get("name", ""),
                        "status": c.get("status", "UNKNOWN"),
                        "spend": spend,
                        "clicks": int(insight.get("clicks", 0)),
                        "impressions": int(insight.get("impressions", 0)),
                        "ctr": float(insight.get("ctr", 0)),
                        "cpc": float(insight.get("cpc", 0)),
                    })
            # Sort by spend descending
            campaigns.sort(key=lambda x: x["spend"], reverse=True)
            return campaigns
        except Exception as e:
            logger.warning(f"Campaign breakdown fetch failed: {e}")
            return []

    # ─── Private: Recommendations ─────────────────────────────────

    @staticmethod
    def _generate_recommendations(metrics: Dict, comparison: Dict) -> List[str]:
        """Generate actionable recommendations from the day's data."""
        recs = []
        meta = metrics.get("meta", {})
        shopify = metrics.get("shopify", {})
        dod = comparison.get("day_over_day", {})

        spend = meta.get("spend", 0)
        clicks = meta.get("clicks", 0)
        revenue = shopify.get("revenue", 0)
        orders = shopify.get("orders", 0)

        if spend > 0 and orders == 0:
            recs.append(
                f"Spent ${spend:.2f} with zero purchases. Check Meta Pixel is firing, "
                "review landing page experience, and verify checkout flow."
            )

        if clicks > 50 and orders == 0:
            recs.append(
                f"{clicks} clicks but no sales. Consider: product page CRO improvements, "
                "adding reviews/trust signals, or retargeting warm visitors."
            )

        if spend > 0 and revenue > 0:
            roas = revenue / spend
            if roas < 1:
                recs.append(
                    f"ROAS is {roas:.2f}x (below breakeven). "
                    "Review ad targeting, pause low-performing ads, increase bids on winners."
                )
            elif roas >= 3:
                recs.append(
                    f"Strong ROAS of {roas:.2f}x. Consider increasing budget on top performers."
                )

        # CPC trending up
        cpc_change = dod.get("spend")
        clicks_change = dod.get("clicks")
        if cpc_change is not None and cpc_change > 20 and (clicks_change is None or clicks_change < 5):
            recs.append(
                "Spend increased significantly without proportional click growth. "
                "CPCs may be rising — review audience overlap and ad fatigue."
            )

        if not meta.get("connected"):
            recs.append("Meta Ads not connected. Configure META_ACCESS_TOKEN and META_AD_ACCOUNT_ID.")

        if not shopify.get("connected"):
            recs.append("Shopify data unavailable. Check Shopify credentials.")

        if not recs:
            recs.append("All metrics within normal range. Keep monitoring.")

        return recs

    # ─── Private: Email Delivery ──────────────────────────────────

    def _send_via_klaviyo(self, to_email: str, subject: str, html_body: str) -> Dict:
        """Send email via Klaviyo transactional email API."""
        from app.database import SettingsModel

        api_key = ""
        try:
            row = self.db.query(SettingsModel).filter(SettingsModel.key == "klaviyo_api_key").first()
            if row and row.value:
                api_key = row.value
        except Exception:
            pass
        if not api_key:
            api_key = os.environ.get("KLAVIYO_API_KEY", "")

        if not api_key:
            return {"success": False, "error": "No Klaviyo API key configured"}

        from_email = os.environ.get("REPORT_FROM_EMAIL", "reports@court-sportswear.com")
        from_name = os.environ.get("REPORT_FROM_NAME", "AutoSEM Reports")

        try:
            resp = requests.post(
                f"{KLAVIYO_BASE_URL}/transactional-email-send/",
                headers={
                    "Authorization": f"Klaviyo-API-Key {api_key}",
                    "revision": KLAVIYO_REVISION,
                    "Content-Type": "application/json",
                },
                json={
                    "data": {
                        "type": "transactional-email",
                        "attributes": {
                            "from_email": from_email,
                            "from_name": from_name,
                            "subject": subject,
                            "to": [{"email": to_email}],
                            "html_body": html_body,
                        },
                    }
                },
                timeout=30,
            )
            if resp.status_code in (200, 201, 202):
                return {"success": True}
            return {"success": False, "error": f"Klaviyo {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _send_via_smtp(to_email: str, subject: str, html_body: str) -> Dict:
        """Send email via SMTP as fallback."""
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")
        from_email = os.environ.get("REPORT_FROM_EMAIL", "reports@court-sportswear.com")

        if not smtp_host or not smtp_user:
            return {"success": False, "error": "SMTP not configured (set SMTP_HOST, SMTP_USER, SMTP_PASS)"}

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── Scheduler Entry Point ────────────────────────────────────────

def run_daily_report():
    """Entry point for the APScheduler job. Generates and sends report."""
    from app.database import SessionLocal, ActivityLogModel

    db = SessionLocal()
    try:
        svc = DailyReportService(db)
        report = svc.generate_report()
        result = svc.send_report(report)

        logger.info(f"Daily report: {result.get('status')} via {result.get('method', 'none')}")

        log = ActivityLogModel(
            action="DAILY_REPORT_SENT" if result.get("status") == "sent" else "DAILY_REPORT_FAILED",
            entity_type="scheduler",
            entity_id="",
            details=(
                f"method={result.get('method', 'none')} | "
                f"to={result.get('to', 'none')} | "
                f"date={report.get('report_date', '?')}"
            ),
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"Daily report job failed: {e}")
        try:
            log = ActivityLogModel(
                action="DAILY_REPORT_FAILED",
                entity_type="scheduler",
                entity_id="",
                details=f"Error: {str(e)}",
            )
            db.add(log)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
