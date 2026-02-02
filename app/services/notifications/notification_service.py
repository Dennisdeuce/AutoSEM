import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from twilio.rest import Client as TwilioClient
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self):
        self.twilio_client = None
        self.sendgrid_client = None

        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            self.twilio_client = TwilioClient(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )

        if settings.SENDGRID_API_KEY:
            self.sendgrid_client = SendGridAPIClient(settings.SENDGRID_API_KEY)

    def send_daily_report(self, report_data: Dict[str, Any]) -> bool:
        """Send daily performance report"""
        subject = f"AutoSEM Daily Report - {datetime.now().strftime('%Y-%m-%d')}"

        html_content = self._generate_daily_report_html(report_data)

        return self._send_email(subject, html_content, "Daily Report")

    def send_alert(self, alert_type: str, message: str, urgent: bool = False) -> bool:
        """Send an alert notification"""
        if urgent:
            # Send SMS for urgent alerts
            self._send_sms_alert(message)

        # Send email alert
        subject = f"AutoSEM Alert: {alert_type}"
        html_content = f"""
        <h2>AutoSEM Alert</h2>
        <p><strong>Type:</strong> {alert_type}</p>
        <p><strong>Message:</strong> {message}</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        """

        # Send Slack notification if configured
        self._send_slack_alert(alert_type, message)

        return self._send_email(subject, html_content, "Alert")

    def send_weekly_report(self, report_data: Dict[str, Any]) -> bool:
        """Send weekly performance report"""
        subject = f"AutoSEM Weekly Report - Week of {datetime.now().strftime('%Y-%m-%d')}"

        html_content = self._generate_weekly_report_html(report_data)

        return self._send_email(subject, html_content, "Weekly Report")

    def send_monthly_report(self, report_data: Dict[str, Any]) -> bool:
        """Send monthly performance report"""
        subject = f"AutoSEM Monthly Report - {datetime.now().strftime('%B %Y')}"

        html_content = self._generate_monthly_report_html(report_data)

        return self._send_email(subject, html_content, "Monthly Report")

    def _send_email(self, subject: str, html_content: str, report_type: str) -> bool:
        """Send email using SendGrid"""
        if not self.sendgrid_client:
            logger.warning("SendGrid not configured, skipping email")
            return False

        try:
            # In a real implementation, you'd get the recipient from settings
            # For now, using a placeholder
            recipient = "owner@court-sportswear.com"

            message = Mail(
                from_email="autosem@court-sportswear.com",
                to_emails=recipient,
                subject=subject,
                html_content=html_content
            )

            response = self.sendgrid_client.send(message)

            if response.status_code == 202:
                logger.info(f"Email sent successfully: {subject}")
                return True
            else:
                logger.error(f"Failed to send email: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False

    def _send_sms_alert(self, message: str) -> bool:
        """Send SMS alert using Twilio"""
        if not self.twilio_client or not settings.TWILIO_PHONE_NUMBER:
            logger.warning("Twilio not configured, skipping SMS")
            return False

        try:
            # In a real implementation, you'd get the recipient from settings
            recipient = "+1234567890"  # Placeholder

            sms = self.twilio_client.messages.create(
                body=f"AutoSEM Alert: {message}",
                from_=settings.TWILIO_PHONE_NUMBER,
                to=recipient
            )

            logger.info(f"SMS sent successfully: {sms.sid}")
            return True

        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            return False

    def _send_slack_alert(self, alert_type: str, message: str) -> bool:
        """Send Slack notification"""
        if not settings.SLACK_WEBHOOK_URL:
            return False

        try:
            payload = {
                "text": f"🚨 *AutoSEM Alert*\n*Type:* {alert_type}\n*Message:* {message}",
                "username": "AutoSEM",
                "icon_emoji": ":robot_face:"
            }

            response = requests.post(
                settings.SLACK_WEBHOOK_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                logger.info("Slack notification sent successfully")
                return True
            else:
                logger.error(f"Failed to send Slack notification: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending Slack notification: {e}")
            return False

    def _generate_daily_report_html(self, data: Dict[str, Any]) -> str:
        """Generate HTML for daily report"""
        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .metric {{ margin: 10px 0; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                .header {{ background-color: #f0f0f0; padding: 10px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>AutoSEM Daily Report</h1>
                <p>Date: {datetime.now().strftime('%Y-%m-%d')}</p>
            </div>

            <h2>Today's Performance</h2>
            <div class="metric">Spend: ${data.get('spend_today', 0):.2f}</div>
            <div class="metric">Revenue: ${data.get('revenue_today', 0):.2f}</div>
            <div class="metric">ROAS: {data.get('roas_today', 0):.2f}x</div>
            <div class="metric">Orders: {data.get('orders_today', 0)}</div>

            <h2>System Status</h2>
            <div class="metric">Status: ✅ {data.get('system_status', 'Operational')}</div>
            <div class="metric">Last Optimization: {data.get('last_optimization', 'Unknown')}</div>
            <div class="metric">Actions Today: {data.get('actions_today', 0)}</div>

            <h2>Top Performers</h2>
            {self._generate_top_performers_html(data.get('top_performers', []))}

            <h2>Actions Taken</h2>
            {self._generate_actions_html(data.get('actions_taken', []))}
        </body>
        </html>
        """

    def _generate_weekly_report_html(self, data: Dict[str, Any]) -> str:
        """Generate HTML for weekly report"""
        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .metric {{ margin: 10px 0; }}
                .trend {{ font-weight: bold; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
            </style>
        </head>
        <body>
            <h1>AutoSEM Weekly Report</h1>
            <p>Week of: {datetime.now().strftime('%Y-%m-%d')}</p>

            <h2>Week-over-Week Trends</h2>
            <div class="metric">Spend: ${data.get('spend_week', 0):.2f} ({data.get('spend_change', 0):+.1f}%)</div>
            <div class="metric">Revenue: ${data.get('revenue_week', 0):.2f} ({data.get('revenue_change', 0):+.1f}%)</div>
            <div class="metric">ROAS: {data.get('roas_week', 0):.2f}x ({data.get('roas_change', 0):+.1f}%)</div>

            <h2>Optimizations Made</h2>
            {self._generate_optimizations_html(data.get('optimizations', []))}
        </body>
        </html>
        """

    def _generate_monthly_report_html(self, data: Dict[str, Any]) -> str:
        """Generate HTML for monthly report"""
        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>AutoSEM Monthly Report</h1>
            <p>Month: {datetime.now().strftime('%B %Y')}</p>

            <h2>Financial Summary</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Total Spend</td><td>${data.get('total_spend', 0):.2f}</td></tr>
                <tr><td>Total Revenue</td><td>${data.get('total_revenue', 0):.2f}</td></tr>
                <tr><td>Net Profit</td><td>${data.get('net_profit', 0):.2f}</td></tr>
                <tr><td>ROAS</td><td>{data.get('overall_roas', 0):.2f}x</td></tr>
            </table>

            <h2>Top Products</h2>
            {self._generate_products_table(data.get('top_products', []))}
        </body>
        </html>
        """

    def _generate_top_performers_html(self, performers: List[Dict[str, Any]]) -> str:
        """Generate HTML for top performers section"""
        if not performers:
            return "<p>No data available</p>"

        html = "<ul>"
        for performer in performers[:5]:
            html += f"<li>{performer.get('name', 'Unknown')}: {performer.get('roas', 0):.2f}x ROAS</li>"
        html += "</ul>"
        return html

    def _generate_actions_html(self, actions: List[str]) -> str:
        """Generate HTML for actions taken section"""
        if not actions:
            return "<p>No actions taken</p>"

        html = "<ul>"
        for action in actions[-10:]:  # Show last 10 actions
            html += f"<li>{action}</li>"
        html += "</ul>"
        return html

    def _generate_optimizations_html(self, optimizations: List[Dict[str, Any]]) -> str:
        """Generate HTML for optimizations section"""
        if not optimizations:
            return "<p>No optimizations made</p>"

        html = "<ul>"
        for opt in optimizations:
            html += f"<li>{opt.get('description', 'Unknown optimization')}</li>"
        html += "</ul>"
        return html

    def _generate_products_table(self, products: List[Dict[str, Any]]) -> str:
        """Generate HTML table for products"""
        if not products:
            return "<p>No data available</p>"

        html = "<table><tr><th>Product</th><th>Spend</th><th>Revenue</th><th>ROAS</th></tr>"
        for product in products[:10]:
            html += f"""
            <tr>
                <td>{product.get('name', 'Unknown')}</td>
                <td>${product.get('spend', 0):.2f}</td>
                <td>${product.get('revenue', 0):.2f}</td>
                <td>{product.get('roas', 0):.2f}x</td>
            </tr>
            """
        html += "</table>"
        return html


notification_service = NotificationService()