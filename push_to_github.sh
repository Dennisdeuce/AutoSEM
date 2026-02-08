#!/bin/bash
set -e
REPO="https://github.com/Dennisdeuce/AutoSEM.git"
BRANCH="main"
echo "Pushing AutoSEM Orchestrator to GitHub..."
if [ ! -d ".git" ]; then git init; git remote add origin "$REPO"; fi
git checkout -B "$BRANCH"
git add -A
git commit -m "feat: Complete AutoSEM orchestrator codebase"
git push -u origin "$BRANCH" --force
echo "Done! Code is live at: https://github.com/Dennisdeuce/AutoSEM"
