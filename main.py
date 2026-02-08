"""
AutoSEM - Autonomous SEM Advertising Engine
Main application entry point
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import engine, Base, get_db
from app.routers import products, campaigns, dashboard, settings, automation, meta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoSEM")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("\ud83d\ude80 AutoSEM starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("\u2705 Database tables created")
    yield
    logger.info("\ud83d\udc4b AutoSEM shutting down...")


app = FastAPI(
    title="AutoSEM",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["automation"])
app.include_router(meta.router, prefix="/api/v1/meta", tags=["meta"])


@app.get("/", summary="Root", description="Redirect to dashboard")
async def root():
    return {"message": "Welcome to AutoSEM", "dashboard": "/dashboard"}


@app.get("/dashboard", summary="Dashboard", description="Serve dashboard page")
async def dashboard_page():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AutoSEM Dashboard</h1><p>Template not found</p>")


@app.get("/health", summary="Health Check")
async def health_check():
    return {"status": "healthy"}


@app.get("/design-doc", summary="Design Document",
         description="Serve design documentation for Google Ads API application",
         response_class=HTMLResponse)
async def design_document():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "design_doc.html")
    if os.path.exists(template_path):
        with open(template_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AutoSEM Design Document</h1>")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
