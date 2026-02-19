"""Deploy webhook - auto-pull from GitHub on push.

Handles Replit environments where the workspace is not a git repo
by initializing one on first deploy.
"""

import os
import hmac
import hashlib
import subprocess
import logging

from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("AutoSEM.Deploy")
router = APIRouter()

DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "autosem-deploy-2026")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
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


def _do_fetch_reset() -> dict:
    """Fetch origin and reset to latest. Returns result dict."""
    initialized = _ensure_git_repo()

    fetch = _run(["git", "fetch", "origin", BRANCH])
    if fetch.returncode != 0:
        return {
            "success": False,
            "error": f"git fetch failed: {fetch.stderr.strip()}",
        }

    reset = _run(["git", "reset", "--hard", f"origin/{BRANCH}"])
    head = _run(["git", "log", "--oneline", "-1"])

    # Write marker file so external monitors know a restart is needed
    try:
        with open("/tmp/autosem-needs-restart", "w") as f:
            f.write(head.stdout.strip())
    except Exception:
        pass  # Non-critical, may not have /tmp on all platforms

    return {
        "success": True,
        "initialized": initialized,
        "fetch": fetch.stdout.strip() or fetch.stderr.strip(),
        "reset": reset.stdout.strip(),
        "head": head.stdout.strip(),
        "message": "Code updated. Republish in Replit UI for changes to take effect.",
    }


def _verify_github_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from GitHub webhook."""
    if not GITHUB_WEBHOOK_SECRET:
        return True  # No secret configured, skip verification

    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


@router.post("/pull", summary="Pull latest code from GitHub")
async def deploy_pull(request: Request):
    """Webhook endpoint: pull latest code from GitHub main branch.
    Called by GitHub Actions on every push to main.
    """
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    try:
        result = _do_fetch_reset()
        if result["success"]:
            logger.info(f"Deploy pull completed: {result.get('head', '')}")
        return result
    except Exception as e:
        logger.error(f"Deploy pull failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/github-webhook", summary="GitHub push webhook")
async def github_webhook(request: Request):
    """Receive GitHub push webhook, verify signature, and pull latest code.

    Set GITHUB_WEBHOOK_SECRET env var to enable signature verification.
    Configure in GitHub repo Settings > Webhooks with content type application/json.
    """
    body = await request.body()

    # Verify signature if secret is configured
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_github_signature(body, signature):
        logger.warning("GitHub webhook signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Only process push events to main branch
    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"status": "pong"}

    try:
        import json
        payload = json.loads(body)
        ref = payload.get("ref", "")
        if ref and ref != f"refs/heads/{BRANCH}":
            return {"status": "skipped", "reason": f"Push to {ref}, not {BRANCH}"}
    except Exception:
        pass  # If we can't parse payload, proceed anyway

    try:
        result = _do_fetch_reset()
        if result["success"]:
            logger.info(f"GitHub webhook deploy completed: {result.get('head', '')}")
        return {"status": "pulled", **result}
    except Exception as e:
        logger.error(f"GitHub webhook deploy failed: {e}")
        return {"status": "error", "error": str(e)}


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
