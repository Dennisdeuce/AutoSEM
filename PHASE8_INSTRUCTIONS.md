# Phase 8 Development Tasks

**Priority: RESTART FIRST, then fix bugs, then features**
**Target version: 1.8.0**

Read CLAUDE.md first — it's been updated with Phase 7 status and all known bugs.

---

## TASK 0 — RESTART THE APP (DO THIS FIRST)

v1.7.0 code is on disk but the process is running v1.6.0. os.execv does NOT work in Replit.

**In Replit Shell, try these in order until one works:**

```bash
# Option A: Find and kill the python process
ps aux | grep python
kill -9 <PID_OF_MAIN_PROCESS>
# Replit's always-on should auto-restart it

# Option B: Kill PID 1 child
kill $(pgrep -f "uvicorn main:app")

# Option C: If nothing else works
# Edit .replit file to add a space, save, remove space, save
# This sometimes triggers a restart
```

**Verify restart worked:**
```bash
curl -s https://auto-sem.replit.app/health | grep version
# Should show 1.7.0
```

If none of these work, just proceed with Phase 8 code changes — user will Republish once at the end.

---

## TASK 1 — Fix Deploy Restart (BUG-4, CRITICAL)

**File:** `app/routers/deploy.py`

Replace the os.execv approach with something that works in Replit:

```python
import subprocess, signal, os, sys

def _restart_app():
    """Restart by exiting — Replit's always-on supervisor restarts the process."""
    import threading
    def do_exit():
        os._exit(0)  # Hard exit, Replit supervisor will restart
    threading.Timer(2.0, do_exit).start()  # 2s delay to send HTTP response first
```

Replace ALL occurrences of `os.execv(sys.executable, ...)` with `_restart_app()`.

**Test:** After deploying, call POST /api/v1/deploy/pull — verify the app comes back at the new version within 30 seconds. If os._exit(0) doesn't trigger auto-restart, try `os.kill(os.getpid(), signal.SIGTERM)` instead.

---

## TASK 2 — Fix Scheduler DB Session (BUG-1, CRITICAL)

**File:** `scheduler.py`

The optimizer job fails because it doesn't pass a DB session. Fix:

```python
from app.database import SessionLocal

def run_optimization_cycle():
    """Run optimization with proper DB session."""
    db = SessionLocal()
    try:
        optimizer = CampaignOptimizer(db)
        results = optimizer.run_optimization()
        # Log results to ActivityLogModel
        activity = ActivityLogModel(
            action="SCHEDULER_OPTIMIZE",
            details=json.dumps(results) if results else "No actions taken",
            timestamp=datetime.utcnow()
        )
        db.add(activity)
        db.commit()
    except Exception as e:
        db.rollback()
        # Log error but don't crash scheduler
        try:
            activity = ActivityLogModel(
                action="SCHEDULER_ERROR",
                details=f"Optimization failed: {str(e)}",
                timestamp=datetime.utcnow()
            )
            db.add(activity)
            db.commit()
        except:
            pass
    finally:
        db.close()
```

Apply the same pattern to ALL scheduler jobs that need DB access (performance sync, etc).

---

## TASK 3 — Dashboard Improvements

**File:** `templates/dashboard.html`

### 3a. Add SEO tab content
The SEO router (Phase 7) added JSON-LD and sitemap endpoints. Add to the SEO & Content tab:
- Link to `/api/v1/seo/sitemap.xml`
- Button to "Generate All JSON-LD" that calls `/api/v1/seo/all-jsonld`
- Display JSON-LD status per product

### 3b. Activity log auto-refresh
In System Health tab, make the activity log auto-refresh every 30 seconds so you can see optimizer actions in real time.

### 3c. Show running version prominently
Add the current version number to the dashboard header (pull from /health endpoint).

---

## TASK 4 — Harden Error Recovery

**File:** `app/database.py` and anywhere SessionLocal() is used

The app sometimes gets stuck in `InFailedSqlTransaction` state where a failed query poisons the connection pool. Add a middleware or utility:

```python
from sqlalchemy.exc import PendingRollbackError

def get_db():
    db = SessionLocal()
    try:
        yield db
    except PendingRollbackError:
        db.rollback()
        yield db
    finally:
        db.close()
```

Also add a GET /api/v1/health/reset-db endpoint that calls `db.rollback()` on a fresh session to clear stuck transactions without restarting.

---

## TASK 5 — Version bump to 1.8.0

**File:** `app/version.py`
Update VERSION = "1.8.0"

---

## Commit message format:
```
Phase 8: Deploy restart fix, scheduler DB session, dashboard improvements, error recovery, v1.8.0

- Task 1: Replace os.execv with os._exit(0) for Replit-compatible restart
- Task 2: Fix scheduler optimizer with proper SessionLocal() DB session
- Task 3: Dashboard SEO tab content, activity log auto-refresh, version display
- Task 4: DB error recovery middleware, /health/reset-db endpoint
- Task 5: Bump VERSION to 1.8.0

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## After push:
1. Pull via: `curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull -H "X-Deploy-Key: autosem-deploy-2026"`
2. If the new restart mechanism works, app should come back as v1.8.0 automatically
3. If not, kill the process in Replit Shell: `kill $(pgrep -f "uvicorn main:app")`
4. Verify: `curl -s https://auto-sem.replit.app/health | grep version`
