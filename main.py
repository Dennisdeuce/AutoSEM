"""AutoSEM - Autonomous SEM Advertising Engine\nMain application entry point"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import engine, Base, get_db
from app.routers import products, campaigns, dashboard, settings, automation, meta, tiktok, deploy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AutoSEM")

VERSION = "0.6.0"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("\U0001f680 AutoSEM starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("\u2705 Database tables created")
    logger.info(f"\u2705 All routers loaded - v{VERSION} TT_USER for all ads (CUSTOMIZED_USER deprecated)")
    yield
    logger.info("\U0001f44b AutoSEM shutting down...")


app = FastAPI(title="AutoSEM", version=VERSION, docs_url="/docs", openapi_url="/api/v1/openapi.json", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Include routers
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["automation"])
app.include_router(meta.router, prefix="/api/v1/meta", tags=["meta"])
app.include_router(tiktok.router, prefix="/api/v1/tiktok", tags=["tiktok"])
app.include_router(deploy.router, prefix="/api/v1/deploy", tags=["deploy"])


@app.get("/", summary="Root")
async def root():
    return {"message": f"Welcome to AutoSEM v{VERSION}", "dashboard": "/dashboard", "tiktok_setup": "/tiktok-setup"}


@app.get("/version", summary="Version")
async def version():
    return {"version": VERSION}


@app.get("/dashboard", summary="Dashboard", response_class=HTMLResponse)
async def dashboard_page():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path) as f:
            content = f.read()
            if 'error-banner' in content and 'tiktok' in content.lower():
                return HTMLResponse(content=content)
    except Exception:
        pass
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/health", summary="Health Check")
async def health_check():
    return {"status": "healthy", "version": VERSION, "tiktok_router": "loaded", "deploy_router": "loaded",
            "features": ["tt_user_identity", "single_image_ads", "single_video_ads", "multi_strategy_ads", "pangle_fallback"],
            "identity_strategy": "TT_USER for all ads (CUSTOMIZED_USER deprecated by TikTok)"}


@app.get("/tiktok-setup", summary="TikTok Setup Page", response_class=HTMLResponse)
async def tiktok_setup_page():
    return HTMLResponse(content=TIKTOK_SETUP_HTML)


@app.get("/design-doc", summary="Design Document", response_class=HTMLResponse)
async def design_document():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "design_doc.html")
    if os.path.exists(template_path):
        with open(template_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AutoSEM Design Document</h1>")


# ── TikTok Setup Page ──
TIKTOK_SETUP_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TikTok Ads Setup - AutoSEM</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; padding: 40px 20px; }
        .container { max-width: 700px; margin: 0 auto; }
        .card { background: white; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; }
        h1 { font-size: 1.8em; margin-bottom: 10px; }
        h2 { font-size: 1.2em; margin-bottom: 12px; color: #333; }
        .subtitle { color: #666; margin-bottom: 20px; }
        .step { padding: 16px; background: #f9fafb; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #667eea; }
        .step h3 { margin-bottom: 6px; }
        .step p { color: #555; font-size: 0.95em; }
        .btn { display: inline-block; padding: 14px 28px; border-radius: 8px; border: none; font-weight: 600; font-size: 1em; cursor: pointer; text-decoration: none; transition: all 0.2s; }
        .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .btn-primary:hover { transform: translateY(-2px); filter: brightness(1.1); }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { transform: translateY(-2px); }
        input[type="text"] { width: 100%; padding: 12px; border: 2px solid #e5e7eb; border-radius: 8px; font-size: 1em; margin-bottom: 12px; }
        input[type="text"]:focus { border-color: #667eea; outline: none; }
        .status { padding: 12px; border-radius: 8px; margin-top: 12px; font-weight: 500; }
        .status.success { background: #d1fae5; color: #065f46; }
        .status.error { background: #fee2e2; color: #991b1b; }
        .status.info { background: #e0e7ff; color: #4338ca; }
        #result { margin-top: 16px; white-space: pre-wrap; font-family: monospace; font-size: 0.85em; max-height: 400px; overflow-y: auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>&#127919; TikTok Ads Setup</h1>
            <p class="subtitle">Connect your TikTok Business account and launch campaigns (v0.6.0 - TT_USER)</p>
            <div id="status-check">Checking connection status...</div>
        </div>

        <div class="card" id="connect-section">
            <h2>Step 1: Connect TikTok Account</h2>
            <div class="step">
                <h3>Option A: Auto-Connect (Recommended)</h3>
                <p>Click the button below to authorize via TikTok OAuth flow:</p>
                <br>
                <a href="/api/v1/tiktok/connect" class="btn btn-primary">&#128279; Connect TikTok Account</a>
            </div>
            <div class="step">
                <h3>Option B: Manual Auth Code</h3>
                <p>If you already have an auth_code from the TikTok redirect URL, paste it here:</p>
                <br>
                <input type="text" id="auth-code-input" placeholder="Paste auth_code here...">
                <button class="btn btn-primary" onclick="exchangeToken()">Exchange Token</button>
                <div id="exchange-result"></div>
            </div>
        </div>

        <div class="card" id="launch-section">
            <h2>Step 2: Launch Campaign</h2>
            <div class="step">
                <h3>Campaign Settings</h3>
                <p>Daily Budget: $20.00 | Objective: Traffic | Target: US Tennis Enthusiasts 25-55</p>
                <p style="margin-top:8px;color:#667eea"><strong>v0.6.0:</strong> Uses TT_USER identity (linked TikTok account) for all ads</p>
            </div>
            <button class="btn btn-success" onclick="launchCampaign()">&#128640; Launch Campaign</button>
            <div id="launch-result"></div>
        </div>

        <div class="card">
            <h2>Debug Tools</h2>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
                <button class="btn btn-primary" onclick="testVideo()" style="font-size:0.9em;padding:10px">&#127909; Generate Test Video</button>
                <button class="btn btn-primary" onclick="checkFfmpeg()" style="font-size:0.9em;padding:10px">&#9881; Check ffmpeg</button>
                <button class="btn btn-primary" onclick="listIdentities()" style="font-size:0.9em;padding:10px">&#128100; List Identities</button>
                <button class="btn btn-primary" onclick="listVideos()" style="font-size:0.9em;padding:10px">&#127910; List Videos</button>
            </div>
            <div id="result"></div>
        </div>
    </div>

    <script>
        async function checkStatus() {
            try {
                const res = await fetch('/api/v1/tiktok/status');
                const data = await res.json();
                const el = document.getElementById('status-check');
                if (data.connected) {
                    el.innerHTML = '<div class="status success">&#9989; TikTok Connected! Advertiser ID: ' + data.advertiser_id + '</div>';
                } else {
                    el.innerHTML = '<div class="status info">&#128268; Not connected yet. Complete Step 1 below.</div>';
                }
            } catch(e) {
                document.getElementById('status-check').innerHTML = '<div class="status error">Error checking status: ' + e.message + '</div>';
            }
        }

        async function exchangeToken() {
            const code = document.getElementById('auth-code-input').value.trim();
            if (!code) { alert('Please paste the auth_code'); return; }
            const el = document.getElementById('exchange-result');
            el.innerHTML = '<div class="status info">Exchanging token...</div>';
            try {
                const res = await fetch('/api/v1/tiktok/exchange-token?auth_code=' + encodeURIComponent(code), { method: 'POST' });
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
                if (data.success) {
                    el.innerHTML = '<div class="status success">&#9989; Token saved! Advertiser ID: ' + data.advertiser_id + '</div>';
                    checkStatus();
                } else {
                    el.innerHTML = '<div class="status error">&#10060; ' + (data.error || 'Failed') + '</div>';
                }
            } catch(e) {
                el.innerHTML = '<div class="status error">Error: ' + e.message + '</div>';
            }
        }

        async function launchCampaign() {
            const el = document.getElementById('launch-result');
            el.innerHTML = '<div class="status info">Launching campaign... This may take 30-60 seconds.</div>';
            try {
                const res = await fetch('/api/v1/tiktok/launch-campaign?daily_budget=20.0&campaign_name=Court+Sportswear+-+Tennis+Ads', { method: 'POST' });
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
                if (data.success) {
                    let msg = '&#9989; Campaign launched! ID: ' + data.campaign_id;
                    if (data.ad_strategy) msg += ' | Strategy: ' + data.ad_strategy;
                    el.innerHTML = '<div class="status success">' + msg + '</div>';
                } else {
                    el.innerHTML = '<div class="status error">&#10060; ' + (data.error || 'Failed') + '</div>';
                }
            } catch(e) {
                el.innerHTML = '<div class="status error">Error: ' + e.message + '</div>';
            }
        }

        async function testVideo() {
            document.getElementById('result').textContent = 'Generating video from product images...';
            try {
                const res = await fetch('/api/v1/tiktok/generate-video', { method: 'POST' });
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
            } catch(e) { document.getElementById('result').textContent = 'Error: ' + e.message; }
        }

        async function checkFfmpeg() {
            try {
                const res = await fetch('/api/v1/tiktok/debug-ffmpeg');
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
            } catch(e) { document.getElementById('result').textContent = 'Error: ' + e.message; }
        }

        async function listIdentities() {
            try {
                const res = await fetch('/api/v1/tiktok/identities');
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
            } catch(e) { document.getElementById('result').textContent = 'Error: ' + e.message; }
        }

        async function listVideos() {
            try {
                const res = await fetch('/api/v1/tiktok/videos');
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
            } catch(e) { document.getElementById('result').textContent = 'Error: ' + e.message; }
        }

        checkStatus();
    </script>
</body>
</html>'''


# ── Inline Dashboard Template ──
DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoSEM Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }
        .container { max-width: 1280px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .header h1 { font-size: 2.2em; margin-bottom: 6px; }
        .header p { font-size: 1.1em; opacity: 0.9; }
        .error-banner { background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #f5c6cb; display: none; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .metric-card { background: white; padding: 22px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); text-align: center; transition: transform 0.2s; }
        .metric-card:hover { transform: translateY(-3px); }
        .metric-value { font-size: 2.2em; font-weight: 700; margin-bottom: 4px; }
        .metric-label { color: #666; font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; }
        .positive { color: #28a745; } .negative { color: #dc3545; } .warning { color: #f59e0b; } .neutral { color: #6366f1; }
        .status-actions-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
        @media (max-width: 768px) { .status-actions-row { grid-template-columns: 1fr; } }
        .status-card { background: white; padding: 22px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }
        .status-dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }
        .status-dot.ok { background: #28a745; } .status-dot.warn { background: #f59e0b; } .status-dot.err { background: #dc3545; }
        .actions-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .action-btn { padding: 14px; border-radius: 8px; border: none; font-weight: 600; font-size: 0.9em; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
        .action-btn:hover { transform: translateY(-2px); filter: brightness(1.05); }
        .action-btn.blue { background: #e0e7ff; color: #4338ca; }
        .action-btn.green { background: #d1fae5; color: #065f46; }
        .action-btn.red { background: #fee2e2; color: #991b1b; }
        .action-btn.gray { background: #f3f4f6; color: #374151; }
        .channel-section { background: white; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); margin-bottom: 24px; overflow: hidden; }
        .channel-header { padding: 18px 22px; display: flex; justify-content: space-between; align-items: center; }
        .channel-header h2 { font-size: 1.15em; display: flex; align-items: center; gap: 10px; }
        .channel-header .badge { font-size: 0.75em; padding: 3px 10px; border-radius: 20px; font-weight: 600; }
        .channel-header .refresh-btn { padding: 6px 14px; border-radius: 6px; border: 1px solid #ddd; background: white; cursor: pointer; font-size: 0.85em; color: #666; transition: all 0.2s; }
        .channel-header .refresh-btn:hover { border-color: #999; color: #333; }
        .meta-header { border-bottom: 3px solid #1877f2; } .meta-badge { background: #e7f0fd; color: #1877f2; }
        .google-header { border-bottom: 3px solid #4285f4; } .google-badge { background: #e8f0fe; color: #1a73e8; }
        .tiktok-header { border-bottom: 3px solid #010101; } .tiktok-badge { background: #f0f0f0; color: #010101; }
        .channel-body { padding: 20px 22px; }
        .channel-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; margin-bottom: 18px; }
        .ch-metric { background: #f9fafb; border-radius: 8px; padding: 14px; text-align: center; }
        .ch-metric .val { font-size: 1.5em; font-weight: 700; color: #1f2937; }
        .ch-metric .lbl { font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }
        .campaign-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
        .campaign-table th { text-align: left; padding: 10px 14px; color: #6b7280; font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #e5e7eb; font-weight: 600; }
        .campaign-table td { padding: 10px 14px; border-bottom: 1px solid #f3f4f6; }
        .campaign-table tr:hover { background: #f9fafb; }
        .status-active, .status-ACTIVE, .status-ENABLE { background: #d1fae5; color: #065f46; display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }
        .status-paused, .status-PAUSED, .status-DISABLE { background: #fef3c7; color: #92400e; display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }
        .activity-section { background: white; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); padding: 22px; }
        .activity-section h2 { margin-bottom: 14px; font-size: 1.15em; }
        .activity-item { padding: 10px 0; border-bottom: 1px solid #f3f4f6; }
        .activity-item:last-child { border-bottom: none; }
        .activity-time { color: #9ca3af; font-size: 0.8em; }
        .activity-desc { margin-top: 2px; font-size: 0.95em; }
        .no-data { color: #9ca3af; text-align: center; padding: 30px; font-style: italic; }
        .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid #e5e7eb; border-top-color: #6366f1; border-radius: 50%; animation: spin 0.7s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading-msg { text-align: center; padding: 30px; color: #9ca3af; }
        .footer { text-align: center; color: #9ca3af; font-size: 0.85em; padding: 20px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>&#128640; AutoSEM Dashboard</h1>
            <p>Court Sportswear &mdash; Autonomous E-Commerce Advertising Engine v0.6.0</p>
        </div>
        <div id="error-banner" class="error-banner"></div>
        <div class="metrics-grid" id="top-metrics">
            <div class="metric-card"><div class="metric-value neutral">--</div><div class="metric-label">Today Spend</div></div>
            <div class="metric-card"><div class="metric-value neutral">--</div><div class="metric-label">Today Revenue</div></div>
            <div class="metric-card"><div class="metric-value neutral">--</div><div class="metric-label">Today ROAS</div></div>
            <div class="metric-card"><div class="metric-value neutral">--</div><div class="metric-label">Today Orders</div></div>
        </div>
        <div class="status-actions-row">
            <div class="status-card">
                <h2><span class="status-dot ok" id="status-dot"></span> System Status: <span id="system-status">Loading...</span></h2>
                <p id="last-opt" style="margin-top:8px;color:#6b7280;font-size:0.95em">Last optimization: --</p>
                <p id="actions-today" style="color:#6b7280;font-size:0.95em">Actions today: --</p>
            </div>
            <div class="status-card">
                <h2 style="margin-bottom:12px">Quick Actions</h2>
                <div class="actions-grid">
                    <button class="action-btn blue" onclick="viewReports()">&#128202; Reports</button>
                    <button class="action-btn green" onclick="syncProducts()">&#128722; Sync Products</button>
                    <button class="action-btn red" onclick="pauseAll()">&#9208;&#65039; Pause All</button>
                    <button class="action-btn gray" onclick="refreshAll()">&#128260; Refresh</button>
                </div>
            </div>
        </div>

        <!-- Meta Ads Section -->
        <div class="channel-section">
            <div class="channel-header meta-header">
                <h2>&#128308; Meta Ads <span class="badge meta-badge" id="meta-status-badge">Loading...</span></h2>
                <button class="refresh-btn" onclick="loadMetaPerformance()">Refresh</button>
            </div>
            <div class="channel-body" id="meta-body"><div class="loading-msg"><div class="spinner"></div> Loading Meta data...</div></div>
        </div>

        <!-- TikTok Ads Section -->
        <div class="channel-section">
            <div class="channel-header tiktok-header">
                <h2>&#127925; TikTok Ads <span class="badge tiktok-badge" id="tiktok-status-badge">Loading...</span></h2>
                <button class="refresh-btn" onclick="loadTikTokPerformance()">Refresh</button>
            </div>
            <div class="channel-body" id="tiktok-body"><div class="loading-msg"><div class="spinner"></div> Loading TikTok data...</div></div>
        </div>

        <!-- Google Ads Section -->
        <div class="channel-section">
            <div class="channel-header google-header">
                <h2>&#128309; Google Ads <span class="badge google-badge" id="google-status-badge">Loading...</span></h2>
                <button class="refresh-btn" onclick="loadGooglePerformance()">Refresh</button>
            </div>
            <div class="channel-body" id="google-body"><div class="loading-msg"><div class="spinner"></div> Loading Google Ads data...</div></div>
        </div>

        <div class="activity-section">
            <h2>Recent Activity</h2>
            <div id="activity-log"><div class="loading-msg"><div class="spinner"></div> Loading activity...</div></div>
        </div>
        <div class="footer">AutoSEM v0.6.0 &mdash; Court Sportswear &mdash; Meta + TikTok + Google Ads &mdash; Auto-refreshes every 60s</div>
    </div>
    <script>
        const API = '/api/v1';
        function showError(msg) { const b = document.getElementById('error-banner'); b.textContent = msg; b.style.display = 'block'; setTimeout(() => b.style.display = 'none', 15000); }
        function hideError() { document.getElementById('error-banner').style.display = 'none'; }

        async function loadDashboardStatus() {
            try {
                const res = await fetch(API + '/dashboard/status');
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const d = await res.json();
                hideError();
                const grid = document.getElementById('top-metrics');
                const roas = d.roas_today || 0;
                const roasClass = roas >= 2 ? 'positive' : roas >= 1 ? 'warning' : 'negative';
                grid.innerHTML = '<div class="metric-card"><div class="metric-value neutral">$' + (d.spend_today||0).toFixed(2) + '</div><div class="metric-label">Today Spend</div></div>' +
                    '<div class="metric-card"><div class="metric-value positive">$' + (d.revenue_today||0).toFixed(2) + '</div><div class="metric-label">Today Revenue</div></div>' +
                    '<div class="metric-card"><div class="metric-value ' + roasClass + '">' + roas.toFixed(1) + 'x</div><div class="metric-label">Today ROAS</div></div>' +
                    '<div class="metric-card"><div class="metric-value neutral">' + (d.orders_today||0) + '</div><div class="metric-label">Today Orders</div></div>';
                document.getElementById('status-dot').className = 'status-dot ' + (d.status === 'operational' ? 'ok' : 'warn');
                document.getElementById('system-status').textContent = d.status || 'Unknown';
                document.getElementById('last-opt').textContent = 'Last optimization: ' + (d.last_optimization || '--');
                document.getElementById('actions-today').textContent = 'Actions today: ' + (d.actions_today || 0);
            } catch(e) { showError('Failed to load dashboard: ' + e.message); }
        }

        async function loadMetaPerformance() {
            const body = document.getElementById('meta-body');
            const badge = document.getElementById('meta-status-badge');
            try {
                const statusRes = await fetch(API + '/meta/status');
                const status = await statusRes.json();
                badge.textContent = status.connected ? 'Connected' : 'Disconnected';
                if (!status.connected) { badge.style.background = '#fee2e2'; badge.style.color = '#991b1b'; }
                const perfRes = await fetch(API + '/dashboard/meta-performance');
                const perf = await perfRes.json();
                if (perf.error) { body.innerHTML = '<div class="no-data">' + perf.error + '</div>'; return; }
                const s = perf.summary || {};
                body.innerHTML = '<div class="channel-metrics">' +
                    '<div class="ch-metric"><div class="val">' + (s.total_campaigns||0) + '</div><div class="lbl">Campaigns</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + (s.total_spend||0).toFixed(2) + '</div><div class="lbl">Spend (7d)</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.total_impressions||0).toLocaleString() + '</div><div class="lbl">Impressions</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.total_clicks||0).toLocaleString() + '</div><div class="lbl">Clicks</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.avg_ctr||0) + '%</div><div class="lbl">CTR</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + (s.avg_cpc||0).toFixed(2) + '</div><div class="lbl">Avg CPC</div></div></div>';
            } catch(e) { body.innerHTML = '<div class="no-data">Failed: ' + e.message + '</div>'; }
        }

        async function loadTikTokPerformance() {
            const body = document.getElementById('tiktok-body');
            const badge = document.getElementById('tiktok-status-badge');
            try {
                const statusRes = await fetch(API + '/tiktok/status');
                const status = await statusRes.json();
                if (status.connected) {
                    badge.textContent = 'Connected';
                    const perfRes = await fetch(API + '/tiktok/performance');
                    const perf = await perfRes.json();
                    if (perf.error) { body.innerHTML = '<div class="no-data">' + perf.error + '</div>'; return; }
                    const s = perf.summary || {};
                    const camps = perf.campaigns || [];
                    let html = '<div class="channel-metrics">' +
                        '<div class="ch-metric"><div class="val">' + (s.total_campaigns||0) + '</div><div class="lbl">Campaigns</div></div>' +
                        '<div class="ch-metric"><div class="val">$' + (s.total_spend||0).toFixed(2) + '</div><div class="lbl">Spend (7d)</div></div>' +
                        '<div class="ch-metric"><div class="val">' + (s.total_impressions||0).toLocaleString() + '</div><div class="lbl">Impressions</div></div>' +
                        '<div class="ch-metric"><div class="val">' + (s.total_clicks||0).toLocaleString() + '</div><div class="lbl">Clicks</div></div>' +
                        '<div class="ch-metric"><div class="val">' + (s.avg_ctr||0) + '%</div><div class="lbl">CTR</div></div>' +
                        '<div class="ch-metric"><div class="val">$' + (s.avg_cpc||0).toFixed(2) + '</div><div class="lbl">Avg CPC</div></div></div>';
                    if (camps.length > 0) {
                        html += '<table class="campaign-table"><thead><tr><th>Campaign</th><th>Status</th><th>Budget</th><th>Objective</th></tr></thead><tbody>';
                        camps.forEach(c => { html += '<tr><td>' + (c.name||'--') + '</td><td><span class="status-' + (c.status||'') + '">' + (c.status||'--') + '</span></td><td>$' + (c.budget||0) + '</td><td>' + (c.objective||'--') + '</td></tr>'; });
                        html += '</tbody></table>';
                    }
                    body.innerHTML = html;
                } else {
                    badge.textContent = 'Not Connected';
                    badge.style.background = '#fee2e2'; badge.style.color = '#991b1b';
                    body.innerHTML = '<div class="no-data">TikTok not connected. <a href="/tiktok-setup" style="color:#667eea">Click here to set up TikTok Ads</a></div>';
                }
            } catch(e) { body.innerHTML = '<div class="no-data">Failed: ' + e.message + '</div>'; }
        }

        async function loadGooglePerformance() {
            const body = document.getElementById('google-body');
            const badge = document.getElementById('google-status-badge');
            try {
                const res = await fetch(API + '/campaigns/');
                const all = await res.json();
                const google = all.filter(c => c.platform === 'google_ads');
                const active = google.filter(c => c.status === 'active');
                badge.textContent = active.length + ' Active';
                const totalSpend = google.reduce((s,c) => s + (c.spend||0) + (c.total_spend||0), 0);
                const totalRevenue = google.reduce((s,c) => s + (c.revenue||0) + (c.total_revenue||0), 0);
                const roas = totalSpend > 0 ? totalRevenue/totalSpend : 0;
                body.innerHTML = '<div class="channel-metrics">' +
                    '<div class="ch-metric"><div class="val">' + google.length + '</div><div class="lbl">Total</div></div>' +
                    '<div class="ch-metric"><div class="val positive">' + active.length + '</div><div class="lbl">Active</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + totalSpend.toFixed(2) + '</div><div class="lbl">Spend</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + totalRevenue.toFixed(2) + '</div><div class="lbl">Revenue</div></div>' +
                    '<div class="ch-metric"><div class="val">' + roas.toFixed(2) + 'x</div><div class="lbl">ROAS</div></div></div>';
            } catch(e) { body.innerHTML = '<div class="no-data">Failed: ' + e.message + '</div>'; }
        }

        async function loadActivity() {
            const c = document.getElementById('activity-log');
            try {
                const res = await fetch(API + '/dashboard/activity?limit=10');
                const logs = await res.json();
                if (!logs || logs.length === 0) { c.innerHTML = '<div class="no-data">No activity yet.</div>'; return; }
                c.innerHTML = logs.map(l => '<div class="activity-item"><div class="activity-time">' + (l.timestamp ? new Date(l.timestamp).toLocaleString() : '--') + '</div><div class="activity-desc"><strong>' + (l.action||'') + '</strong>: ' + (l.details||l.entity_type||'') + '</div></div>').join('');
            } catch(e) { c.innerHTML = '<div class="no-data">Failed to load activity</div>'; }
        }

        async function pauseAll() { if (!confirm('Pause ALL campaigns?')) return; try { const r = await fetch(API+'/dashboard/pause-all',{method:'POST'}); const d = await r.json(); alert('Paused '+d.campaigns_paused+' campaigns'); refreshAll(); } catch(e) { alert('Failed: '+e.message); } }
        function viewReports() { window.open('/docs','_blank'); }
        async function syncProducts() { try { const r = await fetch(API+'/products/sync-shopify',{method:'POST'}); const d = await r.json(); alert('Synced '+(d.synced||d.products_synced||0)+' products'); } catch(e) { alert('Sync failed: '+e.message); } }
        function refreshAll() { hideError(); loadDashboardStatus(); loadMetaPerformance(); loadTikTokPerformance(); loadGooglePerformance(); loadActivity(); }
        refreshAll();
        setInterval(refreshAll, 60000);
    </script>
</body>
</html>'''


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
