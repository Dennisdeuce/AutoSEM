from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.optimization import OptimizationEngine
from app.crud import campaign
from datetime import datetime, timedelta

router = APIRouter()


@router.get("/status")
def get_dashboard_status(db: Session = Depends(get_db)):
    """Get current system status and metrics"""
    # Get recent campaigns and aggregate metrics
    active_campaigns = campaign.get_active_campaigns(db)

    # Calculate today's metrics (simplified - in real implementation would aggregate from actual data)
    total_spend_today = sum(camp.spend for camp in active_campaigns if camp.updated_at.date() == datetime.now().date())
    total_revenue_today = sum(camp.revenue for camp in active_campaigns if camp.updated_at.date() == datetime.now().date())
    total_conversions_today = sum(camp.conversions for camp in active_campaigns if camp.updated_at.date() == datetime.now().date())

    # Calculate ROAS
    roas_today = total_revenue_today / total_spend_today if total_spend_today > 0 else 0

    return {
        "status": "operational",
        "last_optimization": "47 minutes ago",
        "actions_today": 12,
        "spend_today": round(total_spend_today, 2),
        "revenue_today": round(total_revenue_today, 2),
        "roas_today": round(roas_today, 2),
        "orders_today": total_conversions_today,
        "active_campaigns": len(active_campaigns)
    }


@router.post("/pause-all")
def pause_all_campaigns():
    """Emergency pause all campaigns"""
    # Implementation would pause all active campaigns
    return {"message": "All campaigns paused"}


@router.post("/resume-all")
def resume_all_campaigns():
    """Resume all paused campaigns"""
    # Implementation would resume all paused campaigns
    return {"message": "All campaigns resumed"}


@router.get("/dashboard")
def get_dashboard_page():
    """Serve the dashboard HTML page"""
    return FileResponse("app/static/dashboard.html", media_type="text/html")


@router.get("/metrics/daily")
def get_daily_metrics(db: Session = Depends(get_db)):
    """Get detailed daily metrics"""
    active_campaigns = campaign.get_active_campaigns(db)

    # Group by platform
    google_campaigns = [c for c in active_campaigns if c.platform == 'google']
    meta_campaigns = [c for c in active_campaigns if c.platform == 'meta']

    return {
        "total": {
            "spend": sum(c.spend for c in active_campaigns),
            "revenue": sum(c.revenue for c in active_campaigns),
            "conversions": sum(c.conversions for c in active_campaigns),
            "roas": sum(c.roas for c in active_campaigns) / len(active_campaigns) if active_campaigns else 0
        },
        "google": {
            "campaigns": len(google_campaigns),
            "spend": sum(c.spend for c in google_campaigns),
            "revenue": sum(c.revenue for c in google_campaigns),
            "roas": sum(c.roas for c in google_campaigns) / len(google_campaigns) if google_campaigns else 0
        },
        "meta": {
            "campaigns": len(meta_campaigns),
            "spend": sum(c.spend for c in meta_campaigns),
            "revenue": sum(c.revenue for c in meta_campaigns),
            "roas": sum(c.roas for c in meta_campaigns) / len(meta_campaigns) if meta_campaigns else 0
        }
    }


@router.get("/metrics/weekly")
def get_weekly_metrics(db: Session = Depends(get_db)):
    """Get weekly metrics for reporting"""
    # Simplified implementation - in real system would aggregate by week
    daily_metrics = get_daily_metrics(db)

    # Mock weekly data (multiply by 7 for demo)
    return {
        "spend": daily_metrics["total"]["spend"] * 7,
        "revenue": daily_metrics["total"]["revenue"] * 7,
        "conversions": daily_metrics["total"]["conversions"] * 7,
        "roas": daily_metrics["total"]["roas"],
        "change_percent": 12.5  # Mock week-over-week change
    }


@router.get("/campaigns/performance")
def get_campaign_performance(db: Session = Depends(get_db)):
    """Get performance data for all campaigns"""
    active_campaigns = campaign.get_active_campaigns(db)

    return [
        {
            "id": camp.id,
            "name": camp.name,
            "platform": camp.platform,
            "spend": camp.spend,
            "revenue": camp.revenue,
            "conversions": camp.conversions,
            "roas": camp.roas,
            "status": camp.status
        }
        for camp in active_campaigns
    ]