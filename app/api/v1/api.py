from fastapi import APIRouter

from app.api.v1.endpoints import products, campaigns, dashboard, settings
from app.routers import tiktok

api_router = APIRouter()
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(tiktok.router, prefix="/tiktok", tags=["tiktok"])
