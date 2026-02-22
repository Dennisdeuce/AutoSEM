"""AutoSEM - Autonomous Search Engine Marketing Platform

v2.6.0 - Phase 22: Auto-install Meta Pixel on startup (revenue blocker fix)
v2.5.9 - Phase 21: GitHub Actions auto-deploy on push to main (reserved-VM)
v2.5.8 - Phase 20: pytest framework, 63 tests, GitHub Actions CI, smoke test
v2.5.7 - Phase 19: A/B testing with statistical significance and auto-optimization
v2.5.6 - Phase 18: Review solicitation for existing customers (Judge.me + Klaviyo)
v2.5.5 - Phase 17: Conversion campaign creation, objective switching (BUG-16)
v2.5.4 - Phase 16: Automated daily performance report with email delivery
v2.5.3 - Phase 15: Deploy restart fix (BUG-14), status/verify endpoints
v2.5.2 - Phase 14: Meta Pixel installer, conversion audit, TikTok /campaigns
v2.5.1 - Phase 14: TikTok /campaigns endpoint, sync_data fix
v2.5.0 - Phase 13: Klaviyo rewrite, store health monitor, hardcoded key removal
v1.10.0 - Phase 10: Close the data loop
v1.9.0 - Phase 9: Order webhook handler with UTM attribution
"""

import os
import sys
import logging
import threading
import time
from datetime import datetime

from app.version import VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AutoSEM")

def create_app():
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="AutoSEM", description="Autonomous SEM Platform", version=VERSION)

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    templates = None
    if os.path.isdir(templates_dir):
        templates = Jinja2Templates(directory=templates_dir)

    from app.database import init_db
    init_db()

    # Register ALL routers
    router_configs = [
        ("app.routers.dashboard", "/api/v1/dashboard", "Dashboard"),
        ("app.routers.meta", "/api/v1/meta", "Meta"),
        ("app.routers.tiktok", "/api/v1/tiktok", "TikTok"),
        ("app.routers.tiktok_campaigns", "/api/v1/tiktok", "TikTok Campaigns"),
        ("app.routers.campaigns", "/api/v1/campaigns", "Campaigns"),
        ("app.routers.products", "/api/v1/products", "Products"),
        ("app.routers.settings", "/api/v1/settings", "Settings"),
        ("app.routers.automation", "/api/v1/automation", "Automation"),
        ("app.routers.deploy", "/api/v1/deploy", "Deploy"),
        ("app.routers.shopify", "/api/v1/shopify", "Shopify"),
        ("app.routers.google_ads", "/api/v1/google", "Google Ads"),
        ("app.routers.klaviyo", "/api/v1/klaviyo", "Klaviyo"),
        ("app.routers.seo", "/api/v1/seo", "SEO"),
        ("app.routers.health", "/api/v1/health", "Health"),
        ("app.routers.store_health", "/api/v1/store-health", "Store Health"),
        ("app.routers.pixel_installer", "/api/v1/pixel", "Meta Pixel"),
        ("app.routers.conversion_audit", "/api/v1/dashboard", "Conversion Audit"),
    ]

    routers_loaded = []
    for module_path, prefix, tag in router_configs:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            app.include_router(mod.router, prefix=prefix, tags=[tag])
            routers_loaded.append(tag.lower())
        except Exception as e:
            logger.warning(f"{tag} router not loaded: {e}")

    logger.info(f"AutoSEM v{VERSION}: Loaded routers: {', '.join(routers_loaded)}")

    @app.get("/")
    def root():
        return {
            "name": "AutoSEM",
            "version": VERSION,
            "status": "running",
            "routers": routers_loaded,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # -----------------------------------------------------------
    # Startup: scheduler, webhooks, and META PIXEL AUTO-INSTALL
    # -----------------------------------------------------------
    def _auto_install_pixel():
        """Background task: install Meta Pixel if missing.
        
        Runs 30s after startup to ensure DB and Shopify token are ready.
        This is the #1 revenue fix — without the pixel, Meta can't track
        any conversions and all ad spend is blind.
        """
        time.sleep(30)
        logger.info("Pixel auto-installer: checking if Meta Pixel is on court-sportswear.com...")
        
        try:
            import requests as req
            resp = req.get("https://court-sportswear.com", timeout=15)
            body = resp.text.lower()
            
            if "fbq(" in body and "connect.facebook.net" in body:
                logger.info("Pixel auto-installer: Meta Pixel already installed. No action needed.")
                return
            
            logger.warning("Pixel auto-installer: Meta Pixel NOT FOUND. Installing now...")
            
            # Call our own pixel install endpoint
            try:
                install_resp = req.post(
                    "http://localhost:8000/api/v1/pixel/install",
                    timeout=30,
                )
                result = install_resp.json()
                status = result.get("status", "unknown")
                
                if status in ("installed", "already_installed"):
                    logger.info(f"Pixel auto-installer: SUCCESS — {result.get('message', status)}")
                else:
                    logger.error(f"Pixel auto-installer: FAILED — {result}")
            except Exception as e:
                logger.error(f"Pixel auto-installer: could not call install endpoint: {e}")
                # Fallback: log instructions for manual install
                logger.error(
                    "MANUAL FIX: POST https://auto-sem.replit.app/api/v1/pixel/install "
                    "OR run: curl -X POST http://localhost:8000/api/v1/pixel/install"
                )
        except Exception as e:
            logger.error(f"Pixel auto-installer: failed to check storefront: {e}")

    try:
        from scheduler import start_scheduler, stop_scheduler

        @app.on_event("startup")
        def on_startup():
            start_scheduler()
            logger.info("Scheduler started")
            
            # Register Shopify webhooks
            try:
                from app.services.shopify_webhook_register import register_webhooks_on_startup
                register_webhooks_on_startup()
            except Exception as wh_err:
                logger.warning(f"Shopify webhook registration skipped: {wh_err}")
            
            # Auto-install Meta Pixel in background (30s delay)
            pixel_thread = threading.Thread(target=_auto_install_pixel, daemon=True)
            pixel_thread.start()
            logger.info("Meta Pixel auto-installer scheduled (30s delay)")

        @app.on_event("shutdown")
        def on_shutdown():
            stop_scheduler()
            logger.info("Scheduler stopped")
    except Exception as e:
        logger.warning(f"Scheduler not loaded: {e}")

    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "version": VERSION,
            "routers_loaded": routers_loaded,
            "router_count": len(routers_loaded),
        }

    @app.get("/version")
    def version():
        return {"version": VERSION}

    @app.get("/dashboard")
    def dashboard():
        if templates:
            try:
                from starlette.requests import Request
                from starlette.datastructures import URL
                scope = {"type": "http", "method": "GET", "path": "/dashboard", "query_string": b"", "headers": []}
                request = Request(scope)
                return templates.TemplateResponse("dashboard.html", {"request": request, "version": VERSION})
            except Exception as e:
                logger.error(f"Template error: {e}")
                from fastapi.responses import HTMLResponse
                tpl_path = os.path.join(templates_dir, "dashboard.html")
                if os.path.exists(tpl_path):
                    with open(tpl_path) as f:
                        return HTMLResponse(content=f.read())
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"message": "Dashboard template not found", "api_docs": "/docs"})

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
