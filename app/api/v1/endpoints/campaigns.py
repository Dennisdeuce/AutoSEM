from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import crud, models, schemas
from app.db.session import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Campaign])
def read_campaigns(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
):
    campaigns = crud.campaign.get_multi(db, skip=skip, limit=limit)
    return campaigns


@router.get("/{campaign_id}", response_model=schemas.Campaign)
def read_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
):
    campaign = crud.campaign.get(db, id=campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/", response_model=schemas.Campaign)
def create_campaign(
    campaign_in: schemas.CampaignCreate,
    db: Session = Depends(get_db),
):
    campaign = crud.campaign.create(db, obj_in=campaign_in)
    return campaign


@router.put("/{campaign_id}", response_model=schemas.Campaign)
def update_campaign(
    campaign_id: int,
    campaign_in: schemas.CampaignUpdate,
    db: Session = Depends(get_db),
):
    campaign = crud.campaign.get(db, id=campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = crud.campaign.update(db, db_obj=campaign, obj_in=campaign_in)
    return campaign