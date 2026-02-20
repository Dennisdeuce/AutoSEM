"""
Notification Service
Logs important events (orders, auto-actions, spend alerts) to ActivityLogModel and logger.
"""
import logging
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.database import ActivityLogModel

logger = logging.getLogger("autosem.notifications")


class NotificationService:
    """Central notification hub for important platform events."""

    def __init__(self, db: Session):
        self.db = db

    def notify_order(self, order_data: Dict):
        """Log a new order event."""
        order_id = order_data.get("id", "unknown")
        total = order_data.get("total_price", "0")
        email = order_data.get("email", "")
        logger.info(f"ORDER RECEIVED: #{order_id} — ${total} from {email}")
        self._log("ORDER_RECEIVED", "order", str(order_id),
                  f"Order #{order_id}: ${total} from {email}")

    def notify_auto_action(self, action: str, details: str):
        """Log an optimizer auto-action (pause, budget change, scale)."""
        logger.info(f"AUTO_ACTION: {action} — {details}")
        self._log("AUTO_ACTION", "optimizer", action, details)

    def notify_spend_alert(self, campaign_name: str, spend: float, threshold: float):
        """Log a spend threshold warning."""
        logger.warning(f"SPEND ALERT: {campaign_name} — ${spend:.2f} exceeds ${threshold:.2f}")
        self._log("SPEND_ALERT", "campaign", campaign_name,
                  f"Spend ${spend:.2f} exceeds threshold ${threshold:.2f}")

    def _log(self, action: str, entity_type: str, entity_id: str, details: str):
        try:
            log = ActivityLogModel(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details[:500],
                timestamp=datetime.utcnow(),
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to log notification: {e}")
