"""
Campaigns API router - Campaign CRUD operations
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db, CampaignModel, ActivityLogModel
from app.schemas import Campaign, CampaignCreate, CampaignUpdate

logger = logging.getLogger("AutoSEM.Campaigns")
router = APIRouter()


@router.post("/cleanup", summary="Clean up stale campaigns",
             description="Delete campaigns with $0 spend and status not active. Removes phantom/stale records.")
def cleanup_campaigns(db: Session = Depends(get_db)):
    """Remove stale campaigns: $0 spend AND not active status."""
    stale = db.query(CampaignModel).filter(
        ~CampaignModel.status.in_(["active", "ACTIVE", "live"]),
        (CampaignModel.total_spend == None) | (CampaignModel.total_spend == 0),
        (CampaignModel.spend == None) | (CampaignModel.spend == 0),
    ).all()

    deleted_count = len(stale)
    deleted_names = []
    for c in stale:
        deleted_names.append(f"{c.name} (id={c.id}, platform={c.platform}, status={c.status})")
        db.delete(c)

    if deleted_count > 0:
        log = ActivityLogModel(
            action="CAMPAIGN_CLEANUP",
            entity_type="system",
            details=f"Deleted {deleted_count} stale campaigns with $0 spend",
        )
        db.add(log)

    db.commit()

    # Count remaining
    remaining = db.query(CampaignModel).count()
    active = db.query(CampaignModel).filter(
        CampaignModel.status.in_(["active", "ACTIVE", "live"])
    ).count()

    return {
        "status": "ok",
        "deleted": deleted_count,
        "deleted_campaigns": deleted_names[:20],  # Cap output
        "remaining": remaining,
        "active": active,
    }


@router.get("/", response_model=List[Campaign])
def read_campaigns(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(CampaignModel).offset(skip).limit(limit).all()


@router.get("/active", response_model=List[Campaign])
def read_active_campaigns(db: Session = Depends(get_db)):
    """Return only campaigns with status=active."""
    return db.query(CampaignModel).filter(
        CampaignModel.status.in_(["active", "ACTIVE", "live"])
    ).all()


@router.post("/", response_model=Campaign)
def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    db_campaign = CampaignModel(**campaign.dict())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    logger.info(f"Created campaign: {db_campaign.name} on {db_campaign.platform}")
    return db_campaign


@router.get("/{campaign_id}", response_model=Campaign)
def read_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.put("/{campaign_id}", response_model=Campaign)
def update_campaign(campaign_id: int, campaign: CampaignUpdate, db: Session = Depends(get_db)):
    db_campaign = db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
    if not db_campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for key, val in campaign.dict(exclude_unset=True).items():
        setattr(db_campaign, key, val)

    db.commit()
    db.refresh(db_campaign)
    logger.info(f"Updated campaign {campaign_id}: {db_campaign.name}")
    return db_campaign
