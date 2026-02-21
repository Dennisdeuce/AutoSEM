# Ad Creative Variations — Ready to Deploy

## Pre-requisite
These commands require v2.5.0+ to be live (needs Replit Republish).

### Step 1: Get image hashes
```bash
curl -s "https://auto-sem.replit.app/api/v1/meta/ad-images?limit=10"
```
Use the `hash` values from the response below.

### Step 2: Create 3 Ad Variations

**Variation 1: Beer & Tennis Lifestyle**
```bash
curl -X POST "https://auto-sem.replit.app/api/v1/meta/create-ad" \
  -H "Content-Type: application/json" \
  -d '{
    "adset_id": "120206746647380364",
    "name": "Beer Tennis Lifestyle v1",
    "image_hash": "IMAGE_HASH_HERE",
    "primary_text": "Tennis and craft beer — two things that never go out of style. Our Court Sportswear collection brings them together in tees designed for players who know how to have a good time on and off the court. Moisture-wicking, UPF-protected, and ridiculously comfortable. Free shipping on every order.",
    "headline": "Tennis Tees That Match Your Vibe",
    "description": "Shop the full Court Sportswear collection — free shipping included.",
    "link": "https://court-sportswear.com/collections/all-mens-t-shirts",
    "cta": "SHOP_NOW"
  }'
```

**Variation 2: Performance & Quality Focus**
```bash
curl -X POST "https://auto-sem.replit.app/api/v1/meta/create-ad" \
  -H "Content-Type: application/json" \
  -d '{
    "adset_id": "120206746647380364",
    "name": "Performance Quality v1",
    "image_hash": "IMAGE_HASH_HERE",
    "primary_text": "Built for the court, made to impress. Court Sportswear performance tees feature UPF sun protection, moisture-wicking fabric, and premium comfort that lasts. Look great during warm-ups, feel great during match point. Every shirt ships free — straight to your door.",
    "headline": "Performance Tennis Apparel",
    "description": "UPF protection. Moisture-wicking. Free shipping on all orders.",
    "link": "https://court-sportswear.com/collections/all-mens-t-shirts",
    "cta": "SHOP_NOW"
  }'
```

**Variation 3: Gift / Occasion Angle**
```bash
curl -X POST "https://auto-sem.replit.app/api/v1/meta/create-ad" \
  -H "Content-Type: application/json" \
  -d '{
    "adset_id": "120206746647380364",
    "name": "Tennis Gift Angle v1",
    "image_hash": "IMAGE_HASH_HERE",
    "primary_text": "Know someone who lives for tennis? These Court Sportswear tees make the perfect gift for the player in your life. From retro gaming designs to clever beer-inspired prints — each shirt is made-to-order, performance-grade, and ships free. They will love it. Guaranteed.",
    "headline": "The Perfect Gift for Tennis Players",
    "description": "Unique designs. Premium quality. Free shipping.",
    "link": "https://court-sportswear.com/collections/all-mens-t-shirts",
    "cta": "SHOP_NOW"
  }'
```

## Ad Copy Summary

| Variation | Angle | Headline | Key Hooks |
|-----------|-------|----------|-----------|
| 1 | Lifestyle | Tennis Tees That Match Your Vibe | Beer + tennis culture, fun, comfort |
| 2 | Performance | Performance Tennis Apparel | UPF protection, moisture-wicking, quality |
| 3 | Gift | The Perfect Gift for Tennis Players | Gift-giving, unique designs, made-to-order |

All ads target: `/collections/all-mens-t-shirts` (deep-link, not homepage)
All ads use: SHOP_NOW CTA, free shipping mention
