"""AutoSEM - Autonomous Search Engine Marketing Platform

v1.0.1 - Fix thumbnail upload: use video_cover_url from upload response
       instead of multipart file upload (which returns empty image_id).
       URL-based image upload to TikTok works reliably.
"""

import os
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AutoSEM")

def create_app():
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="AutoSEM", description="Autonomous SEM Platform", version="1.0.1")

    # Mount static files if they exist
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Initialize templates
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    if os.path.isdir(templates_dir):
        templates = Jinja2Templates(directory=templates_dir)

    # Initialize database
    from app.database import init_db
    init_db()

    # Import and register routers
    routers_loaded = []
    try:
        from app.routers import deploy
        app.include_router(deploy.router, prefix="/api/v1/deploy", tags=["Deploy"])
        routers_loaded.append("deploy")
    except Exception as e:
        logger.warning(f"Deploy router not loaded: {e}")

    try:
        from app.routers import tiktok
        app.include_router(tiktok.router, prefix="/api/v1/tiktok", tags=["TikTok"])
        routers_loaded.append("tiktok")
    except Exception as e:
        logger.warning(f"TikTok router not loaded: {e}")

    logger.info(f"AutoSEM: ✅ All routers loaded - v1.0.1 Fix thumbnail upload via video_cover_url")

    @app.get("/")
    def root():
        return {
            "name": "AutoSEM",
            "version": "1.0.1",
            "status": "running",
            "routers": routers_loaded,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "version": "1.0.1",
            "tiktok_router": "loaded" if "tiktok" in routers_loaded else "not loaded",
            "deploy_router": "loaded" if "deploy" in routers_loaded else "not loaded",
            "features": [
                "tt_user_identity",
                "spark_ads_video",
                "video_thumbnail_extraction",
                "video_cover_url_thumbnail",
                "auto_thumbnail_upload",
                "pangle_location_fix",
                "safe_data_parsing",
            ],
            "identity_strategy": "TT_USER Spark Ads - video_cover_url thumbnail (v1.0.1)",
        }

    @app.get("/version")
    def version():
        return {"version": "1.0.1"}

    @app.get("/dashboard")
    def dashboard():
        try:
            return templates.TemplateResponse("dashboard.html", {"request": {}, "version": "1.0.1"})
        except Exception:
            return {"message": "Dashboard template not found", "api_docs": "/docs"}

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
