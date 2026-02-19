"""AutoSEM - Autonomous Search Engine Marketing Platform

v1.3.0 - Add: Shopify integration router with auto-refresh client_credentials tokens
v1.2.0 - Add: Campaign management, interest targeting, targeted campaigns
v1.1.0 - Complete dashboard rebuild with TikTok metrics + aggregate top boxes
       - All routers registered (dashboard, meta, tiktok, campaigns, etc.)
       - Top 4 summary boxes aggregate across all ad platforms
"""

import os
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AutoSEM")

def create_app():
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="AutoSEM", description="Autonomous SEM Platform", version="1.3.0")

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
        ("app.routers.campaigns", "/api/v1/campaigns", "Campaigns"),
        ("app.routers.products", "/api/v1/products", "Products"),
        ("app.routers.settings", "/api/v1/settings", "Settings"),
        ("app.routers.automation", "/api/v1/automation", "Automation"),
        ("app.routers.deploy", "/api/v1/deploy", "Deploy"),
        ("app.routers.shopify", "/api/v1/shopify", "Shopify"),
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

    logger.info(f"AutoSEM v1.3.0: Loaded routers: {', '.join(routers_loaded)}")

    @app.get("/")
    def root():
        return {
            "name": "AutoSEM",
            "version": "1.3.0",
            "status": "running",
            "routers": routers_loaded,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "version": "1.3.0",
            "routers_loaded": routers_loaded,
            "router_count": len(routers_loaded),
        }

    @app.get("/version")
    def version():
        return {"version": "1.3.0"}

    @app.get("/dashboard")
    def dashboard():
        if templates:
            try:
                from starlette.requests import Request
                from starlette.datastructures import URL
                scope = {"type": "http", "method": "GET", "path": "/dashboard", "query_string": b"", "headers": []}
                request = Request(scope)
                return templates.TemplateResponse("dashboard.html", {"request": request, "version": "1.3.0"})
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
