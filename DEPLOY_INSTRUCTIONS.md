# AutoSEM Deploy Instructions

## Quick Deploy (API)

```bash
# 1. Pull latest code from GitHub
curl -X POST https://auto-sem.replit.app/api/v1/deploy/pull \
  -H "X-Deploy-Key: autosem-deploy-2026"

# 2. Wait ~5 seconds, then verify
curl https://auto-sem.replit.app/api/v1/deploy/status

# 3. If versions don't match, force restart
curl -X POST https://auto-sem.replit.app/api/v1/deploy/verify \
  -H "X-Deploy-Key: autosem-deploy-2026"
```

## Understanding the Two Environments

Replit has **two separate environments**:

| Environment | Updated by | Restart method |
|-------------|-----------|---------------|
| **Workspace** (dev) | `POST /deploy/pull` | Automatic (SIGTERM/exit) |
| **Production** (autoscale) | Replit UI only | Republish in Deployments |

`POST /deploy/pull` updates the **workspace** code and restarts the dev server. It does **NOT** update production. Production is an immutable build that only changes when you Republish.

## Full Production Deploy

1. Push code to GitHub (`git push origin main`)
2. Pull to workspace: `POST /api/v1/deploy/pull` with `X-Deploy-Key` header
3. Verify workspace: `GET /api/v1/deploy/status` (check `version_match: true`)
4. **Republish**: Replit Dashboard > Deployments > Republish
5. Verify production: `GET /api/v1/deploy/status` on production URL

## Deploy Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/deploy/pull` | POST | X-Deploy-Key | Fetch + reset to origin/main, restart |
| `/api/v1/deploy/status` | GET | None | Version diagnostics (running vs disk vs git) |
| `/api/v1/deploy/verify` | POST | X-Deploy-Key | Check versions, force restart if mismatched |
| `/api/v1/deploy/github-webhook` | POST | X-Hub-Signature-256 | Auto-deploy on GitHub push |

## Manual Fallback

If the API deploy doesn't work:

```bash
# In Replit Shell:
git pull origin main
kill 1
```

`kill 1` kills the PID 1 process (the run command), which Replit's supervisor automatically restarts.

## Troubleshooting

**`/deploy/status` shows version mismatch after pull:**
- The process didn't restart. Try `POST /deploy/verify` to trigger another restart.
- If that doesn't work: Replit Shell > `kill 1`
- For production: Republish in Replit Deployments UI.

**`/deploy/pull` returns git fetch error:**
- Check that the Replit workspace has internet access
- Verify the GitHub repo is public or credentials are configured

**Production shows old version after Republish:**
- Clear browser cache
- Wait 30-60 seconds for the autoscale deployment to propagate
- Check `/health` or `/version` endpoint for the running version
