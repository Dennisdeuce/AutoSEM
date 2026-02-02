from fastapi import APIRouter, Depends
from app.core.config import settings

router = APIRouter()


@router.get("/")
def get_settings():
    """Get current system settings"""
    return {
        "daily_spend_limit": settings.DAILY_SPEND_LIMIT,
        "monthly_spend_limit": settings.MONTHLY_SPEND_LIMIT,
        "min_roas_threshold": settings.MIN_ROAS_THRESHOLD,
        "emergency_pause_loss": settings.EMERGENCY_PAUSE_LOSS
    }


@router.put("/")
def update_settings(settings_update: dict):
    """Update system settings"""
    # In a real implementation, this would update the settings
    # and persist them to a database or config file
    return {"message": "Settings updated", "settings": settings_update}