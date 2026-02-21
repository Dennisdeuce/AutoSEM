"""
Campaigns API router - Campaign CRUD operations + AI ad copy generation
"""

import os
import json
import logging
from typing import List, Optional
from datetime import datetime

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, CampaignModel, ActivityLogModel
from app.schemas import Campaign, CampaignCreate, CampaignUpdate

logger = logging.getLogger("AutoSEM.Campaigns")
router = APIRouter()

# In-memory cache for API key (set via /set-anthropic-key or env var)
_anthropic_key_cache = {"key": ""}


# ─── Ad Copy Generation Models ────────────────────────────────────

class GenerateAdCopyRequest(BaseModel):
    product_name: str
    product_description: Optional[str] = None
    product_price: Optional[float] = None
    product_url: Optional[str] = None
    target_audience: Optional[str] = "tennis and pickleball players"
    platform: str = "meta"


class SetAnthropicKeyRequest(BaseModel):
    api_key: str


@router.post("/set-anthropic-key", summary="Set Anthropic API key at runtime",
             description="Store the Anthropic API key in memory for AI ad copy generation. "
                         "Persists until app restart. Use when env var isn't available.")
def set_anthropic_key(req: SetAnthropicKeyRequest):
    """Set the Anthropic API key without needing env vars or Republish."""
    if not req.api_key or len(req.api_key) < 10:
        return {"status": "error", "message": "Invalid API key"}
    _anthropic_key_cache["key"] = req.api_key
    prefix = req.api_key[:12] + "..."
    logger.info(f"Anthropic API key set via endpoint: {prefix}")
    return {"status": "ok", "key_prefix": prefix, "message": "Key stored in memory. Will persist until app restart."}


def _get_anthropic_key() -> str:
    """Get Anthropic API key from cache first, then env var."""
    if _anthropic_key_cache["key"]:
        return _anthropic_key_cache["key"]
    return os.environ.get("ANTHROPIC_API_KEY", "")


@router.post("/purge-phantoms", summary="Purge phantom campaigns",
             description="Delete campaigns where status is archived/deleted, total_spend is 0, "
                         "and platform_campaign_id is null. These are local-only records that "
                         "never ran on any ad platform.")
def purge_phantoms(db: Session = Depends(get_db)):
    """Delete phantom campaigns that have no platform link and zero spend."""
    phantoms = db.query(CampaignModel).filter(
        CampaignModel.status.in_(["archived", "deleted"]),
        (CampaignModel.total_spend == None) | (CampaignModel.total_spend == 0),
        CampaignModel.platform_campaign_id == None,
    ).all()

    deleted_names = []
    for c in phantoms:
        deleted_names.append(f"{c.name} (id={c.id}, platform={c.platform})")
        db.delete(c)

    if phantoms:
        db.add(ActivityLogModel(
            action="CAMPAIGN_PURGE",
            entity_type="system",
            details=f"Purged {len(phantoms)} phantom campaigns (archived/deleted, no platform_id, $0 spend)",
        ))

    db.commit()

    remaining = db.query(CampaignModel).count()
    active = db.query(CampaignModel).filter(
        CampaignModel.status.in_(["active", "ACTIVE", "live"])
    ).count()

    return {
        "purged": len(phantoms),
        "purged_campaigns": deleted_names[:50],
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


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Delete a single campaign by ID. Protected campaigns (114, 115) cannot be deleted."""
    PROTECTED = {114, 115}
    if campaign_id in PROTECTED:
        raise HTTPException(status_code=403, detail=f"Campaign {campaign_id} is protected")
    campaign = db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    name = campaign.name
    db.delete(campaign)
    db.commit()
    logger.info(f"Deleted campaign {campaign_id}: {name}")
    return {"deleted": campaign_id, "name": name}


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
                         "Stores winning copy in campaign headlines/descriptions fields. "
                         "If ANTHROPIC_API_KEY env var is not set, use POST /set-anthropic-key first.")
def generate_ad_copy(req: GenerateAdCopyRequest, db: Session = Depends(get_db)):
    """Generate 3 ad copy variants for a product using Claude AI.

    Uses requests library directly (no anthropic SDK needed).
    Key lookup: in-memory cache (set via /set-anthropic-key) → env var.
    """
    api_key = _get_anthropic_key()
    if not api_key:
        return {
            "status": "error",
            "message": "ANTHROPIC_API_KEY not configured. Use POST /api/v1/campaigns/set-anthropic-key to set it.",
        }

    try:
        user_prompt = f"""Generate 3 ad copy variants for this product:

Product: {req.product_name}
Description: {req.product_description or 'N/A'}
Price: ${req.product_price:.2f if req.product_price else 'N/A'}
URL: {req.product_url or 'https://court-sportswear.com'}
Target audience: {req.target_audience}
Platform: {req.platform}

Return JSON array of 3 variants. Each variant must have: headline, primary_text, description, cta"""

        # Call Anthropic API directly via requests (no SDK dependency)
        resp = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20250929",
                "max_tokens": 1024,
                "system": AD_COPY_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=30,
        )

        if resp.status_code != 200:
            error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:500]
            return {"status": "error", "message": f"Anthropic API returned {resp.status_code}", "detail": error_body}

        data = resp.json()
        raw_text = data["content"][0]["text"].strip()
        input_tokens = data.get("usage", {}).get("input_tokens", 0)
        output_tokens = data.get("usage", {}).get("output_tokens", 0)

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
            "model_used": "claude-haiku-4-5-20250929",
            "tokens_used": {
                "input": input_tokens,
                "output": output_tokens,
            },
        }

    except Exception as e:
        logger.error(f"Ad copy generation failed: {e}")
        return {"status": "error", "message": str(e)}
