"""Deploy webhook - auto-pull from GitHub on push.

Handles Replit environments where the workspace is not a git repo
by initializing one on first deploy.
"""

import os
import subprocess
import logging

from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("AutoSEM.Deploy")
router = APIRouter()

DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "autosem-deploy-2026")
REPO_URL = "https://github.com/Dennisdeuce/AutoSEM.git"
BRANCH = "main"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command with sensible defaults."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)


def _ensure_git_repo():
    """Initialize git repo + remote if .git doesn't exist (Replit deploys)."""
    if os.path.isdir(".git"):
        return False  # already a git repo

    logger.info("No .git found — initializing repo for deploy")
    _run(["git", "init"])
    _run(["git", "remote", "add", "origin", REPO_URL])
    return True


@router.post("/pull", summary="Pull latest code from GitHub")
async def deploy_pull(request: Request):
    """Webhook endpoint: pull latest code from GitHub main branch.
    Called by GitHub Actions on every push to main.
    """
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    try:
        initialized = _ensure_git_repo()

        fetch = _run(["git", "fetch", "origin", BRANCH])
        if fetch.returncode != 0:
            return {
                "success": False,
                "error": f"git fetch failed: {fetch.stderr.strip()}",
            }

        reset = _run(["git", "reset", "--hard", f"origin/{BRANCH}"])
        head = _run(["git", "log", "--oneline", "-1"])

        result = {
            "success": True,
            "initialized": initialized,
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
        if not os.path.isdir(".git"):
            return {
                "branch": None,
                "recent_commits": [],
                "message": "Not a git repo — deploy/pull will initialize on first call.",
            }

        head = _run(["git", "log", "--oneline", "-3"])
        branch = _run(["git", "branch", "--show-current"])
        return {
            "branch": branch.stdout.strip(),
            "recent_commits": head.stdout.strip().split("\n"),
        }
    except Exception as e:
        return {"error": str(e)}
