"""
Campaigns API router - Campaign CRUD operations
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db, CampaignModel
from app.schemas import Campaign, CampaignCreate, CampaignUpdate

logger = logging.getLogger("AutoSEM.Campaigns")
router = APIRouter()

@router.get("/", response_model=List[Campaign])
def read_campaigns(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(CampaignModel).offset(skip).limit(limit).all()

@router.post("/", response_model=Campaign)
def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    db_campaign = CampaignModel(**campaign.dict())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
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
    return db_campaign
