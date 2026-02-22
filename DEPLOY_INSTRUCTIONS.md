# AutoSEM Deploy Instructions

## How It Works (Fully Automated)

AutoSEM uses **reserved-vm** deployment on Replit with **GitHub Actions** auto-deploy:

1. Push code to GitHub (`main` branch)
2. GitHub Actions automatically calls `POST /api/v1/deploy/pull`
3. Replit pulls latest code, installs dependencies, and restarts
4. Production is live with new code in ~15 seconds

**No manual Republish needed.** Ever.

## Manual Deploy (if needed)

```bash
# Trigger deploy manually
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"

# Wait ~10 seconds, then verify
curl https://auto-sem.replit.app/api/v1/deploy/status

# If versions don't match, force restart
curl -X POST https://auto-sem.replit.app/api/v1/deploy/verify \
  -H "X-Deploy-Key: autosem-deploy-2026"
```

## Deploy Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/deploy/pull` | POST | X-Deploy-Key | Fetch + reset to origin/main, install deps, restart |
| `/api/v1/deploy/status` | GET | None | Version diagnostics (running vs disk vs git) |
| `/api/v1/deploy/verify` | POST | X-Deploy-Key | Check versions, force restart if mismatched |
| `/api/v1/deploy/github-webhook` | POST | X-Hub-Signature-256 | Auto-deploy on GitHub push (alternative to Actions) |

## Architecture

**Deployment type:** Reserved VM (persistent process)
- Production runs as a persistent uvicorn process on Replit
- `deploy/pull` does `git fetch + reset --hard + pip install + process restart`
- Process restart uses 3-phase strategy: SIGTERM > execv > sys.exit
- New code is picked up from disk on restart — no container rebuild needed

**Auto-deploy flow:**
```
GitHub push > Actions workflow > POST /deploy/pull > git pull > pip install > restart > live
```

## GitHub Actions Setup

The workflow at `.github/workflows/deploy.yml` runs on every push to `main`.

**Required secret:** `DEPLOY_KEY` = the deploy key value
(Set in GitHub repo > Settings > Secrets and variables > Actions)

## Manual Fallback

If the API deploy doesn't work:

```bash
# In Replit Shell:
git fetch origin main && git reset --hard origin/main
pip install -r requirements.txt
kill 1
```

`kill 1` kills PID 1 (the run command), which Replit's supervisor automatically restarts.

## Troubleshooting

**`/deploy/status` shows version mismatch after pull:**
- The process didn't restart. Try `POST /deploy/verify` to trigger another restart.
- If that doesn't work: Replit Shell > `kill 1`

**GitHub Actions deploy fails:**
- Check the `DEPLOY_KEY` secret is set correctly in GitHub repo settings
- Check that auto-sem.replit.app is reachable (Replit may be down)
- Check Actions logs in GitHub > Actions tab

**`/deploy/pull` returns git fetch error:**
- Check that the Replit workspace has internet access
- Verify the GitHub repo is accessible
