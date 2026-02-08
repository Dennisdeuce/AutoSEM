"""
Settings API router - System configuration
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db, SettingsModel

logger = logging.getLogger("AutoSEM.Settings")
router = APIRouter()

DEFAULT_SETTINGS = {
    "daily_spend_limit": "200.0",
    "monthly_spend_limit": "5000.0",
    "min_roas_threshold": "1.5",
    "emergency_pause_loss": "500.0",
}


def _get_setting(db: Session, key: str, default: str = None) -> str:
    s = db.query(SettingsModel).filter(SettingsModel.key == key).first()
    if s:
        return s.value
    return default


def _set_setting(db: Session, key: str, value: str):
    s = db.query(SettingsModel).filter(SettingsModel.key == key).first()
    if s:
        s.value = value
    else:
        s = SettingsModel(key=key, value=value)
        db.add(s)
    db.commit()


@router.get("/", summary="Get Settings",
            description="Get current system settings")
def get_settings(db: Session = Depends(get_db)):
    return {
        "daily_spend_limit": float(_get_setting(db, "daily_spend_limit", DEFAULT_SETTINGS["daily_spend_limit"])),
        "monthly_spend_limit": float(_get_setting(db, "monthly_spend_limit", DEFAULT_SETTINGS["monthly_spend_limit"])),
        "min_roas_threshold": float(_get_setting(db, "min_roas_threshold", DEFAULT_SETTINGS["min_roas_threshold"])),
        "emergency_pause_loss": float(_get_setting(db, "emergency_pause_loss", DEFAULT_SETTINGS["emergency_pause_loss"])),
    }


@router.put("/", summary="Update Settings",
            description="Update system settings")
def update_settings(settings_update: dict, db: Session = Depends(get_db)):
    for key, value in settings_update.items():
        _set_setting(db, key, str(value))
    logger.info(f"Settings updated: {list(settings_update.keys())}")
    return get_settings(db)
