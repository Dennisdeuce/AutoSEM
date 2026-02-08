"""
Meta Ads OAuth router - Handle Meta platform authentication
"""

import os
import logging

import requests
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db, MetaTokenModel

logger = logging.getLogger("AutoSEM.Meta")
router = APIRouter()

META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_REDIRECT_URI = os.environ.get("META_REDIRECT_URI", "https://auto-sem.replit.app/api/v1/meta/callback")


@router.get("/connect", summary="Connect Meta",
            description="Redirect to Meta OAuth authorization")
def connect_meta():
    if not META_APP_ID:
        return {"error": "META_APP_ID not configured"}

    auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_REDIRECT_URI}"
        f"&scope=ads_management,ads_read,business_management"
        f"&response_type=code"
    )
    return RedirectResponse(url=auth_url)


@router.get("/callback", summary="OAuth Callback",
            description="Handle Meta OAuth callback")
def oauth_callback(
    code: str = Query(None),
    error: str = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return HTMLResponse(content=f"<h1>Error</h1><p>{error}</p>")

    if not code:
        return HTMLResponse(content="<h1>Error</h1><p>No auth code received</p>")

    try:
        token_url = (
            f"https://graph.facebook.com/v19.0/oauth/access_token"
            f"?client_id={META_APP_ID}"
            f"&redirect_uri={META_REDIRECT_URI}"
            f"&client_secret={META_APP_SECRET}"
            f"&code={code}"
        )
        resp = requests.get(token_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        short_token = data.get("access_token")
        if not short_token:
            return HTMLResponse(content="<h1>Error</h1><p>No token received</p>")

        long_url = (
            f"https://graph.facebook.com/v19.0/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={META_APP_ID}"
            f"&client_secret={META_APP_SECRET}"
            f"&fb_exchange_token={short_token}"
        )
        long_resp = requests.get(long_url, timeout=30)
        long_resp.raise_for_status()
        long_data = long_resp.json()

        long_token = long_data.get("access_token", short_token)

        existing = db.query(MetaTokenModel).first()
        if existing:
            existing.access_token = long_token
            existing.token_type = "long_lived"
        else:
            token_record = MetaTokenModel(
                access_token=long_token,
                token_type="long_lived",
            )
            db.add(token_record)
        db.commit()

        logger.info("✅ Meta OAuth token saved successfully")
        return HTMLResponse(content="""
            <h1>✅ Meta Connected!</h1>
            <p>Long-lived token saved. You can close this window.</p>
            <script>setTimeout(() => window.close(), 3000)</script>
        """)

    except Exception as e:
        logger.error(f"Meta OAuth failed: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")


@router.get("/status", summary="Check Meta Status",
            description="Check current Meta token status")
def check_meta_status(db: Session = Depends(get_db)):
    token = db.query(MetaTokenModel).first()
    if not token or not token.access_token:
        return {"connected": False, "message": "No Meta token found"}

    try:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/me?access_token={token.access_token}",
            timeout=10,
        )
        if resp.status_code == 200:
            return {
                "connected": True,
                "token_type": token.token_type,
                "updated_at": token.updated_at.isoformat() if token.updated_at else None,
            }
        else:
            return {"connected": False, "message": "Token expired or invalid"}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@router.post("/refresh", summary="Refresh Meta Token",
             description="Refresh the current Meta access token")
def refresh_meta_token(db: Session = Depends(get_db)):
    token = db.query(MetaTokenModel).first()
    if not token or not token.access_token:
        return {"status": "error", "message": "No token to refresh"}

    try:
        url = (
            f"https://graph.facebook.com/v19.0/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={META_APP_ID}"
            f"&client_secret={META_APP_SECRET}"
            f"&fb_exchange_token={token.access_token}"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        new_token = data.get("access_token")
        if new_token:
            token.access_token = new_token
            db.commit()
            return {"status": "refreshed"}

        return {"status": "error", "message": "No token in response"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
