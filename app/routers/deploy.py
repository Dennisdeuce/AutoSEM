"""Deploy webhook - auto-pull from GitHub on push."""

import os
import subprocess
import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("AutoSEM.Deploy")
router = APIRouter()

DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "autosem-deploy-2026")


@router.post("/pull", summary="Pull latest code from GitHub")
async def deploy_pull(request: Request):
    """Webhook endpoint: pull latest code from GitHub main branch.
    Called by GitHub Actions on every push to main.
    """
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    try:
        fetch = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True, text=True, timeout=30
        )
        reset = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            capture_output=True, text=True, timeout=30
        )
        head = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=10
        )

        result = {
            "success": True,
            "fetch": fetch.stdout.strip() or fetch.stderr.strip(),
            "reset": reset.stdout.strip(),
            "head": head.stdout.strip(),
            "message": "Code updated. Restart or republish for changes to take effect.",
        }
        logger.info(f"Deploy pull completed: {head.stdout.strip()}")
        return result

    except Exception as e:
        logger.error(f"Deploy pull failed: {e}")
        return {"success": False, "error": str(e)}


@router.get("/status", summary="Check deploy status")
async def deploy_status():
    """Check current deployed commit."""
    try:
        head = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            capture_output=True, text=True, timeout=10
        )
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=10
        )
        return {
            "branch": branch.stdout.strip(),
            "recent_commits": head.stdout.strip().split("\n"),
        }
    except Exception as e:
        return {"error": str(e)}
