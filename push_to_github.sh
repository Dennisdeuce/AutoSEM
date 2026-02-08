#!/bin/bash
# AutoSEM - Push to GitHub
# Run this from inside the autosem/ folder
#
# Usage:
#   cd autosem
#   chmod +x push_to_github.sh
#   ./push_to_github.sh

set -e

REPO="https://github.com/Dennisdeuce/AutoSEM.git"
BRANCH="main"

echo "🚀 Pushing AutoSEM Orchestrator to GitHub..."

# Initialize git if needed
if [ ! -d ".git" ]; then
    git init
    git remote add origin "$REPO"
fi

# Ensure we're on main
git checkout -B "$BRANCH"

# Stage all files
git add -A

# Commit
git commit -m "feat: Complete AutoSEM orchestrator codebase

- FastAPI application with full API (products, campaigns, dashboard, automation, settings)
- Shopify product sync from Court Sportswear store
- Google Ads + Meta Ads campaign generation and management
- Automated optimization engine with ROAS-based budget adjustments
- Safety mechanisms (spend limits, emergency pause, loss threshold)
- Dashboard UI with real-time metrics and activity log
- Meta OAuth integration
- Docker deployment config
- Matches live deployment at auto-sem.replit.app"

# Force push (overwrites existing sparse repo)
echo ""
echo "Pushing to $REPO ..."
git push -u origin "$BRANCH" --force

echo ""
echo "✅ Done! Code is live at: https://github.com/Dennisdeuce/AutoSEM"
