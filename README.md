# AutoSEM Orchestrator

Fully automated SEM (Search Engine Marketing) campaign engine for **Court Sportswear** — a print-on-demand tennis apparel brand.

AutoSEM automatically syncs products from Shopify, generates optimized Google Ads and Meta (Facebook/Instagram) campaigns, manages budgets based on ROAS targets, and continuously optimizes performance with minimal manual intervention.

## Features

- **Product Sync** — Pulls products from Shopify automatically
- **Campaign Generation** — Creates Google Ads + Meta campaigns with category-aware ad copy and keywords
- **Automated Optimization** — Budget adjustments, bid management, and campaign pausing based on ROAS
- **Safety Mechanisms** — Daily/monthly spend limits, emergency pause at loss threshold
- **Dashboard** — Real-time monitoring UI with campaign metrics and activity log
- **Meta OAuth** — Built-in OAuth flow for Meta Ads authentication

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env with your credentials
docker-compose up --build
```

### Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
uvicorn main:app --reload --port 8000
```

Visit `http://localhost:8000` for the dashboard.

## API Docs

FastAPI auto-generates interactive docs at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

See `/design-doc` for the full architecture and endpoint reference.

## Architecture

```
Shopify → Product Sync → Campaign Generator → Google Ads / Meta APIs
                                    ↓
                        Performance Sync ← Ad Platforms
                                    ↓
                            Optimizer Engine
                                    ↓
                        Budget/Bid Adjustments
```

## Safety Limits

| Setting | Default |
|---------|---------|
| Daily Spend Limit | $200 |
| Monthly Spend Limit | $5,000 |
| Min ROAS Threshold | 1.5x |
| Emergency Pause (Net Loss) | $500 |

## Project Structure

```
autosem/
├── main.py                    # FastAPI app entry point
├── app/
│   ├── database.py            # SQLAlchemy models & DB connection
│   ├── schemas.py             # Pydantic request/response schemas
│   ├── routers/
│   │   ├── products.py        # Product CRUD + Shopify sync
│   │   ├── campaigns.py       # Campaign CRUD
│   │   ├── dashboard.py       # Dashboard metrics & controls
│   │   ├── automation.py      # Orchestrator engine
│   │   ├── settings.py        # Safety settings management
│   │   └── meta.py            # Meta OAuth flow
│   └── services/
│       ├── campaign_generator.py  # Ad campaign creation logic
│       ├── optimizer.py           # Performance optimization engine
│       ├── google_ads.py          # Google Ads API interface
│       └── meta_ads.py            # Meta Marketing API interface
├── templates/
│   ├── dashboard.html         # Dashboard UI
│   └── design_doc.html        # Architecture documentation
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Live Deployment

Production instance: [auto-sem.replit.app](https://auto-sem.replit.app)

---

Built for Court Sportswear — [court-sportswear.com](https://court-sportswear.com)
