"""
Campaigns API router - Campaign CRUD operations + AI ad copy generation
"""

import os
import json
import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, CampaignModel, ActivityLogModel
from app.schemas import Campaign, CampaignCreate, CampaignUpdate

logger = logging.getLogger("AutoSEM.Campaigns")
router = APIRouter()


# ─── Ad Copy Generation Models ────────────────────────────────────

class GenerateAdCopyRequest(BaseModel):
    product_name: str
    product_description: Optional[str] = None
    product_price: Optional[float] = None
    product_url: Optional[str] = None
    target_audience: Optional[str] = "tennis and pickleball players"
    platform: str = "meta"


@router.delete("/cleanup", summary="Purge phantom campaigns",
               description="Delete campaigns with zero spend/clicks/impressions, preserving the two known active Meta campaigns.")
def cleanup_campaigns(db: Session = Depends(get_db)):
    """Purge phantom campaigns: $0 spend, 0 clicks, 0 impressions — except known active campaigns."""
    PROTECTED_IDS = ["120241759616260364", "120206746647300364"]

    stale = db.query(CampaignModel).filter(
        (CampaignModel.total_spend == None) | (CampaignModel.total_spend == 0),
        (CampaignModel.clicks == None) | (CampaignModel.clicks == 0),
        (CampaignModel.impressions == None) | (CampaignModel.impressions == 0),
        ~CampaignModel.platform_campaign_id.in_(PROTECTED_IDS),
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
            details=f"Purged {deleted_count} phantom campaigns (zero spend/clicks/impressions)",
        )
        db.add(log)

    db.commit()

    remaining = db.query(CampaignModel).count()
    active = db.query(CampaignModel).filter(
        CampaignModel.status.in_(["active", "ACTIVE", "live"])
    ).count()

    return {
        "deleted": deleted_count,
        "deleted_campaigns": deleted_names[:20],
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


# ─── AI Ad Copy Generation ────────────────────────────────────────

AD_COPY_SYSTEM_PROMPT = """You are an expert digital advertising copywriter for Court Sportswear, a tennis and pickleball apparel e-commerce brand. You write high-converting Meta (Facebook/Instagram) ad copy.

Rules:
- Headlines: max 40 characters, punchy and benefit-driven
- Primary text: 2-3 sentences, emphasize comfort/performance/style
- Description: 1 sentence, include a clear CTA
- Always mention free shipping if applicable
- Use active voice, avoid superlatives like "best" or "amazing"
- Target audience: tennis and pickleball players who value quality athletic wear

Return ONLY valid JSON — no markdown, no code fences, no explanation.
Return an array of exactly 3 variant objects, each with keys: headline, primary_text, description, cta"""


@router.post("/generate", summary="Generate AI ad copy variants",
             description="Uses Claude API to generate 3 ad copy variants for a product. "
                         "Stores winning copy in campaign headlines/descriptions fields.")
def generate_ad_copy(req: GenerateAdCopyRequest, db: Session = Depends(get_db)):
    """Generate 3 ad copy variants for a product using Claude AI."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "ANTHROPIC_API_KEY not configured"}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        user_prompt = f"""Generate 3 ad copy variants for this product:

Product: {req.product_name}
Description: {req.product_description or 'N/A'}
Price: ${req.product_price:.2f if req.product_price else 'N/A'}
URL: {req.product_url or 'https://court-sportswear.com'}
Target audience: {req.target_audience}
Platform: {req.platform}

Return JSON array of 3 variants. Each variant must have: headline, primary_text, description, cta"""

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=AD_COPY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()

        # Parse the JSON response
        try:
            variants = json.loads(raw_text)
        except json.JSONDecodeError:
            # Try to extract JSON from potential markdown fences
            if "```" in raw_text:
                json_block = raw_text.split("```")[1]
                if json_block.startswith("json"):
                    json_block = json_block[4:]
                variants = json.loads(json_block.strip())
            else:
                return {
                    "status": "error",
                    "message": "Failed to parse AI response as JSON",
                    "raw_response": raw_text[:500],
                }

        if not isinstance(variants, list) or len(variants) == 0:
            return {"status": "error", "message": "AI returned invalid format", "raw_response": raw_text[:500]}

        # Store the best variant (first one) in a new draft campaign
        best = variants[0]
        campaign = CampaignModel(
            platform=req.platform,
            name=f"AI: {req.product_name[:50]}",
            status="draft",
            campaign_type="ai_generated",
            daily_budget=5.0,
            headlines=json.dumps([v.get("headline", "") for v in variants]),
            descriptions=json.dumps([v.get("primary_text", "") for v in variants]),
        )
        db.add(campaign)

        # Log the generation
        log = ActivityLogModel(
            action="AI_AD_COPY_GENERATED",
            entity_type="campaign",
            details=f"Generated 3 variants for '{req.product_name}' via Claude API",
        )
        db.add(log)
        db.commit()
        db.refresh(campaign)

        return {
            "status": "ok",
            "campaign_id": campaign.id,
            "variants": variants,
            "model_used": "claude-haiku-4-5",
            "tokens_used": {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
        }

    except Exception as e:
        logger.error(f"Ad copy generation failed: {e}")
        return {"status": "error", "message": str(e)}
