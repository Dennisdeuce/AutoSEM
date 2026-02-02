from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import engine
from app.db.base import Base

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set up CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    """Redirect to dashboard"""
    return {"message": "Welcome to AutoSEM", "dashboard": "/dashboard"}

@app.get("/dashboard")
def dashboard():
    """Serve dashboard page"""
    from fastapi.responses import FileResponse
    return FileResponse("app/static/dashboard.html", media_type="text/html")

@app.get("/health")
def health_check():
    return {"status": "healthy"}