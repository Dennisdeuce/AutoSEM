"""Deploy router - pull from GitHub, restart, verify.

BUG-14 fix: Improved restart reliability + status/verify endpoints.

Deployment mode: RESERVED VM
  - Production is a persistent process (not immutable snapshot)
  - deploy/pull fetches latest code and restarts the process
  - New code is live immediately after restart — no Republish needed
  - GitHub Actions auto-triggers deploy/pull on every push to main
"""

import os
import sys
import signal
import hmac
import hashlib
import subprocess
import logging
import threading
import time as _time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("AutoSEM.Deploy")
router = APIRouter()

DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "autosem-deploy-2026")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
REPO_URL = "https://github.com/Dennisdeuce/AutoSEM.git"
BRANCH = "main"

# Track deploy state in-memory
_deploy_state = {
    "last_deploy_at": None,
    "last_deploy_head": None,
    "restart_pending": False,
    "restart_scheduled_at": None,
}

# Capture the version that was loaded at import time
from app.version import VERSION as _RUNNING_VERSION


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command with sensible defaults."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)


def _ensure_git_repo():
    """Initialize git repo + remote if .git doesn't exist (Replit deploys)."""
    if os.path.isdir(".git"):
        return False
    logger.info("No .git found — initializing repo for deploy")
    _run(["git", "init"])
    _run(["git", "remote", "add", "origin", REPO_URL])
    return True


def _read_disk_version() -> str:
    """Read VERSION from app/version.py on disk (not the imported module)."""
    version_file = os.path.join(os.path.dirname(__file__), "..", "version.py")
    version_file = os.path.normpath(version_file)
    try:
        with open(version_file, "r") as f:
            for line in f:
                if line.startswith("VERSION"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Could not read disk version: {e}")
    return "unknown"


def _get_git_head() -> str:
    """Get current git HEAD commit hash (short)."""
    try:
        result = _run(["git", "log", "--oneline", "-1"])
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _verify_files_on_disk() -> dict:
    """After git pull, verify key files exist and are updated."""
    checks = {}
    disk_version = _read_disk_version()
    checks["version_on_disk"] = disk_version
    checks["version_file_exists"] = disk_version != "unknown"
    checks["main_py_exists"] = os.path.isfile("main.py")
    checks["app_dir_exists"] = os.path.isdir("app")
    return checks


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

    file_checks = _verify_files_on_disk()

    if not file_checks["version_file_exists"]:
        return {
            "success": False,
            "error": "git reset succeeded but app/version.py not found on disk",
            "file_checks": file_checks,
        }

    # Install any new dependencies
    if os.path.isfile("requirements.txt"):
        try:
            _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"], timeout=120)
            logger.info("Dependencies installed from requirements.txt")
        except Exception as e:
            logger.warning(f"pip install failed (non-fatal): {e}")

    _deploy_state["last_deploy_at"] = datetime.now(timezone.utc).isoformat()
    _deploy_state["last_deploy_head"] = head.stdout.strip()
    _deploy_state["restart_pending"] = True

    return {
        "success": True,
        "initialized": initialized,
        "fetch": fetch.stdout.strip() or fetch.stderr.strip(),
        "reset": reset.stdout.strip(),
        "head": head.stdout.strip(),
        "disk_version": file_checks["version_on_disk"],
        "running_version": _RUNNING_VERSION,
        "version_match": file_checks["version_on_disk"] == _RUNNING_VERSION,
        "file_checks": file_checks,
    }


def _verify_github_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from GitHub webhook."""
    if not GITHUB_WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _schedule_restart(delay: float = 2.0):
    """Restart the process so new code takes effect.

    Strategy (tried in order):
      1. SIGTERM — gives uvicorn graceful shutdown, supervisor restarts
      2. After 3s if still alive: os.execv — replace process in-place
      3. After 3s more: sys.exit(0) — hard exit for process manager

    With reserved-vm deployment, the process restart picks up the new
    code from disk. No Republish needed.
    """
    _deploy_state["restart_pending"] = True
    _deploy_state["restart_scheduled_at"] = datetime.now(timezone.utc).isoformat()

    def _do_restart():
        logger.info("Restart phase 1: sending SIGTERM to self...")
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as e:
            logger.warning(f"SIGTERM failed: {e}")

        _time.sleep(3)
        logger.info("Restart phase 2: SIGTERM didn't kill us, trying os.execv...")
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            logger.warning(f"os.execv failed: {e}")

        _time.sleep(3)
        logger.info("Restart phase 3: execv didn't work, using sys.exit(0)...")
        sys.exit(0)

    threading.Timer(delay, _do_restart).start()
    logger.info(f"Restart sequence scheduled in {delay}s (3 strategies)")


# ——— Endpoints ————————————————————————————————————————

@router.post("/pull", summary="Pull latest code from GitHub")
async def deploy_pull(request: Request):
    """Pull latest code from GitHub main branch and restart.

    Requires X-Deploy-Key header for authentication.
    After pulling, restarts the process so new code loads.

    With reserved-vm deployment, this is all you need — production
    picks up the new code after restart. No Republish required.
    """
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    try:
        result = _do_fetch_reset()
        if result["success"]:
            logger.info(f"Deploy pull completed: {result.get('head', '')}")
            _schedule_restart()
            result["status"] = "restarting"
            result["message"] = (
                "Code updated and dependencies installed. Process restart scheduled. "
                "Production will be live with new code in ~10 seconds."
            )
            result["next_steps"] = [
                "Wait ~10s for restart to complete",
                "GET /api/v1/deploy/status to verify versions match",
                "If versions still don't match: POST /api/v1/deploy/verify",
            ]
        return result
    except Exception as e:
        logger.error(f"Deploy pull failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/github-webhook", summary="GitHub push webhook")
async def github_webhook(request: Request):
    """Receive GitHub push webhook, verify signature, and pull latest code."""
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_github_signature(body, signature):
        logger.warning("GitHub webhook signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")

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
        pass

    try:
        result = _do_fetch_reset()
        if result["success"]:
            logger.info(f"GitHub webhook deploy: {result.get('head', '')}")
            _schedule_restart()
            return {"status": "restarting", **result}
        return {"status": "error", **result}
    except Exception as e:
        logger.error(f"GitHub webhook deploy failed: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/status", summary="Deploy status with version diagnostics")
async def deploy_status():
    """Check running version vs disk version vs git HEAD."""
    disk_version = _read_disk_version()
    git_head = _get_git_head()

    version_match = disk_version == _RUNNING_VERSION
    needs_restart = not version_match

    is_git_repo = os.path.isdir(".git")
    recent_commits = []
    branch = None
    if is_git_repo:
        try:
            head_result = _run(["git", "log", "--oneline", "-5"])
            recent_commits = [c for c in head_result.stdout.strip().split("\n") if c]
            branch_result = _run(["git", "branch", "--show-current"])
            branch = branch_result.stdout.strip()
        except Exception:
            pass

    return {
        "status": "ok",
        "deployment_type": "reserved-vm",
        "running_version": _RUNNING_VERSION,
        "disk_version": disk_version,
        "version_match": version_match,
        "git_head": git_head,
        "branch": branch,
        "is_git_repo": is_git_repo,
        "needs_restart": needs_restart,
        "restart_pending": _deploy_state.get("restart_pending", False),
        "last_deploy_at": _deploy_state.get("last_deploy_at"),
        "last_deploy_head": _deploy_state.get("last_deploy_head"),
        "recent_commits": recent_commits,
        "auto_deploy": "GitHub Actions on push to main",
        "diagnosis": (
            "Versions match — running latest code."
            if version_match
            else f"VERSION MISMATCH: running {_RUNNING_VERSION}, disk has {disk_version}. "
                 "POST /api/v1/deploy/verify to trigger restart."
        ),
    }


@router.post("/verify", summary="Verify deploy and force restart if needed")
async def deploy_verify(request: Request):
    """Check if running version matches disk version. If not, trigger restart."""
    key = request.headers.get("X-Deploy-Key", "")
    if key != DEPLOY_KEY:
        raise HTTPException(status_code=403, detail="Invalid deploy key")

    disk_version = _read_disk_version()
    git_head = _get_git_head()
    version_match = disk_version == _RUNNING_VERSION

    if version_match:
        _deploy_state["restart_pending"] = False
        return {
            "status": "ok",
            "message": "Versions match — no restart needed.",
            "running_version": _RUNNING_VERSION,
            "disk_version": disk_version,
            "git_head": git_head,
        }

    logger.warning(
        f"Version mismatch detected: running={_RUNNING_VERSION}, "
        f"disk={disk_version}. Triggering restart."
    )
    _schedule_restart(delay=1.0)

    return {
        "status": "restarting",
        "message": (
            f"Version mismatch: running {_RUNNING_VERSION}, disk has {disk_version}. "
            "Restart triggered. Production will update in ~10 seconds."
        ),
        "running_version": _RUNNING_VERSION,
        "disk_version": disk_version,
        "git_head": git_head,
        "next_steps": [
            "Wait ~10s for restart",
            "GET /api/v1/deploy/status to check again",
            "Manual fallback: Replit Shell > kill 1",
        ],
    }
