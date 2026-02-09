"""
AutoSEM - Autonomous SEM Advertising Engine
Main application entry point
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import engine, Base, get_db
from app.routers import products, campaigns, dashboard, settings, automation, meta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoSEM")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("🚀 AutoSEM starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created")
    yield
    logger.info("👋 AutoSEM shutting down...")


app = FastAPI(
    title="AutoSEM",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["campaigns"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["automation"])
app.include_router(meta.router, prefix="/api/v1/meta", tags=["meta"])


@app.get("/", summary="Root", description="Redirect to dashboard")
async def root():
    return {"message": "Welcome to AutoSEM", "dashboard": "/dashboard"}


@app.get("/dashboard", summary="Dashboard", description="Serve dashboard page")
async def dashboard_page():
    # Try file first, fall back to inline template
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path) as f:
            content = f.read()
            # Verify it's the updated template (has error-banner div)
            if 'error-banner' in content and 'BID INCREASE' not in content:
                return HTMLResponse(content=content)
            else:
                logger.warning("Stale dashboard template detected, serving inline version")
    except Exception as e:
        logger.warning(f"Could not read template file: {e}")

    # Inline fallback - guaranteed correct template
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/health", summary="Health Check")
async def health_check():
    return {"status": "healthy"}


@app.get("/design-doc", summary="Design Document",
         description="Serve design documentation for Google Ads API application",
         response_class=HTMLResponse)
async def design_document():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "design_doc.html")
    if os.path.exists(template_path):
        with open(template_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AutoSEM Design Document</h1>")


# ── Inline Dashboard Template (fallback for deployment caching issues) ──
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
        .positive { color: #28a745; }
        .negative { color: #dc3545; }
        .warning { color: #f59e0b; }
        .neutral { color: #6366f1; }
        .status-actions-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
        @media (max-width: 768px) { .status-actions-row { grid-template-columns: 1fr; } }
        .status-card { background: white; padding: 22px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }
        .status-dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }
        .status-dot.ok { background: #28a745; }
        .status-dot.warn { background: #f59e0b; }
        .status-dot.err { background: #dc3545; }
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
        .meta-header { border-bottom: 3px solid #1877f2; }
        .meta-badge { background: #e7f0fd; color: #1877f2; }
        .google-header { border-bottom: 3px solid #4285f4; }
        .google-badge { background: #e8f0fe; color: #1a73e8; }
        .channel-body { padding: 20px 22px; }
        .channel-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; margin-bottom: 18px; }
        .ch-metric { background: #f9fafb; border-radius: 8px; padding: 14px; text-align: center; }
        .ch-metric .val { font-size: 1.5em; font-weight: 700; color: #1f2937; }
        .ch-metric .lbl { font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }
        .campaign-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
        .campaign-table th { text-align: left; padding: 10px 14px; color: #6b7280; font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #e5e7eb; font-weight: 600; }
        .campaign-table td { padding: 10px 14px; border-bottom: 1px solid #f3f4f6; }
        .campaign-table tr:hover { background: #f9fafb; }
        .campaign-table .status { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }
        .status-active, .status-ACTIVE { background: #d1fae5; color: #065f46; }
        .status-paused, .status-PAUSED { background: #fef3c7; color: #92400e; }
        .status-deleted { background: #f3f4f6; color: #9ca3af; }
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
            <p>Court Sportswear &mdash; Autonomous E-Commerce Advertising Engine</p>
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
                    <button class="action-btn blue" onclick="viewReports()">&#128202; View Full Reports</button>
                    <button class="action-btn green" onclick="syncProducts()">&#128722; Sync Products</button>
                    <button class="action-btn red" onclick="pauseAll()">&#9208;&#65039; Pause All Campaigns</button>
                    <button class="action-btn gray" onclick="refreshAll()">&#128260; Refresh Data</button>
                </div>
            </div>
        </div>
        <div class="channel-section">
            <div class="channel-header meta-header">
                <h2>&#128308; Meta Ads Performance <span class="badge meta-badge" id="meta-status-badge">Loading...</span></h2>
                <button class="refresh-btn" onclick="loadMetaPerformance()">Refresh</button>
            </div>
            <div class="channel-body" id="meta-body">
                <div class="loading-msg"><div class="spinner"></div> Loading Meta data...</div>
            </div>
        </div>
        <div class="channel-section">
            <div class="channel-header google-header">
                <h2>&#128309; Google Ads Performance <span class="badge google-badge" id="google-status-badge">Loading...</span></h2>
                <button class="refresh-btn" onclick="loadGooglePerformance()">Refresh</button>
            </div>
            <div class="channel-body" id="google-body">
                <div class="loading-msg"><div class="spinner"></div> Loading Google Ads data...</div>
            </div>
        </div>
        <div class="activity-section">
            <h2>Recent Activity</h2>
            <div id="activity-log">
                <div class="loading-msg"><div class="spinner"></div> Loading activity...</div>
            </div>
        </div>
        <div class="footer">AutoSEM Orchestrator v1.0 &mdash; Court Sportswear &mdash; Auto-refreshes every 60s</div>
    </div>
    <script>
        const API = '/api/v1';
        function showError(msg) {
            const banner = document.getElementById('error-banner');
            banner.textContent = msg;
            banner.style.display = 'block';
            setTimeout(() => { banner.style.display = 'none'; }, 15000);
        }
        function hideError() {
            document.getElementById('error-banner').style.display = 'none';
        }
        async function loadDashboardStatus() {
            try {
                const res = await fetch(`${API}/dashboard/status`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                hideError();
                const grid = document.getElementById('top-metrics');
                const roas = d.roas_today || 0;
                const roasClass = roas >= 2 ? 'positive' : roas >= 1 ? 'warning' : 'negative';
                grid.innerHTML = `
                    <div class="metric-card"><div class="metric-value neutral">$${(d.spend_today || 0).toFixed(2)}</div><div class="metric-label">Today Spend</div></div>
                    <div class="metric-card"><div class="metric-value positive">$${(d.revenue_today || 0).toFixed(2)}</div><div class="metric-label">Today Revenue</div></div>
                    <div class="metric-card"><div class="metric-value ${roasClass}">${roas.toFixed(1)}x</div><div class="metric-label">Today ROAS</div></div>
                    <div class="metric-card"><div class="metric-value neutral">${d.orders_today || 0}</div><div class="metric-label">Today Orders</div></div>
                `;
                const statusClass = d.status === 'operational' ? 'ok' : d.status === 'degraded' ? 'warn' : 'ok';
                document.getElementById('status-dot').className = 'status-dot ' + statusClass;
                document.getElementById('system-status').textContent = d.status || 'Unknown';
                document.getElementById('last-opt').textContent = 'Last optimization: ' + (d.last_optimization || '--');
                document.getElementById('actions-today').textContent = 'Actions today: ' + (d.actions_today || 0);
                if (d.error) showError('Dashboard running in degraded mode: ' + d.error);
            } catch(e) {
                showError('Failed to load dashboard data: ' + e.message);
                console.error('Status load failed:', e);
            }
        }
        async function loadMetaPerformance() {
            const body = document.getElementById('meta-body');
            const badge = document.getElementById('meta-status-badge');
            try {
                const statusRes = await fetch(`${API}/meta/status`);
                const status = await statusRes.json();
                if (status.connected) {
                    const days = status.days_remaining;
                    badge.textContent = days ? 'Connected \u2022 ' + days + 'd remaining' : 'Connected';
                    badge.className = 'badge meta-badge';
                } else {
                    badge.textContent = 'Disconnected';
                    badge.style.background = '#fee2e2';
                    badge.style.color = '#991b1b';
                }
                const perfRes = await fetch(`${API}/dashboard/meta-performance`);
                const perf = await perfRes.json();
                if (perf.error) { body.innerHTML = '<div class="no-data">' + perf.error + '</div>'; return; }
                const s = perf.summary || {};
                const campaigns = perf.campaigns || [];
                let html = '<div class="channel-metrics">' +
                    '<div class="ch-metric"><div class="val">' + (s.total_campaigns || 0) + '</div><div class="lbl">Campaigns</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + (s.total_spend || 0).toFixed(2) + '</div><div class="lbl">Spend (7d)</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.total_impressions || 0).toLocaleString() + '</div><div class="lbl">Impressions</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.total_clicks || 0).toLocaleString() + '</div><div class="lbl">Clicks</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.total_reach || 0).toLocaleString() + '</div><div class="lbl">Reach</div></div>' +
                    '<div class="ch-metric"><div class="val">' + (s.avg_ctr || 0) + '%</div><div class="lbl">CTR</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + (s.avg_cpc || 0).toFixed(2) + '</div><div class="lbl">Avg CPC</div></div>' +
                '</div>';
                if (campaigns.length > 0) {
                    html += '<table class="campaign-table"><thead><tr><th>Campaign</th><th>Status</th><th>Spend</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>CPC</th></tr></thead><tbody>';
                    campaigns.forEach(function(c) {
                        html += '<tr><td>' + (c.name||'--') + '</td><td><span class="status status-' + c.status + '">' + c.status + '</span></td><td>$' + (c.spend||0).toFixed(2) + '</td><td>' + (c.impressions||0).toLocaleString() + '</td><td>' + (c.clicks||0) + '</td><td>' + (c.ctr||0) + '%</td><td>$' + (c.cpc||0).toFixed(2) + '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                body.innerHTML = html;
            } catch(e) {
                body.innerHTML = '<div class="no-data">Failed to load Meta data: ' + e.message + '</div>';
            }
        }
        async function loadGooglePerformance() {
            const body = document.getElementById('google-body');
            const badge = document.getElementById('google-status-badge');
            try {
                const res = await fetch(`${API}/campaigns/`);
                const all = await res.json();
                const google = all.filter(function(c) { return c.platform === 'google_ads'; });
                const active = google.filter(function(c) { return c.status === 'active'; });
                const totalSpend = google.reduce(function(s,c) { return s + (c.spend||0) + (c.total_spend||0); }, 0);
                const totalRevenue = google.reduce(function(s,c) { return s + (c.revenue||0) + (c.total_revenue||0); }, 0);
                const totalConversions = google.reduce(function(s,c) { return s + (c.conversions||0); }, 0);
                const roas = totalSpend > 0 ? (totalRevenue / totalSpend) : 0;
                badge.textContent = active.length + ' Active';
                badge.className = 'badge google-badge';
                let html = '<div class="channel-metrics">' +
                    '<div class="ch-metric"><div class="val">' + google.length + '</div><div class="lbl">Total</div></div>' +
                    '<div class="ch-metric"><div class="val positive">' + active.length + '</div><div class="lbl">Active</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + totalSpend.toFixed(2) + '</div><div class="lbl">Total Spend</div></div>' +
                    '<div class="ch-metric"><div class="val">$' + totalRevenue.toFixed(2) + '</div><div class="lbl">Total Revenue</div></div>' +
                    '<div class="ch-metric"><div class="val">' + totalConversions + '</div><div class="lbl">Conversions</div></div>' +
                    '<div class="ch-metric"><div class="val">' + roas.toFixed(2) + 'x</div><div class="lbl">ROAS</div></div>' +
                '</div>';
                if (active.length > 0) {
                    html += '<table class="campaign-table"><thead><tr><th>Campaign</th><th>Status</th><th>Budget/Day</th><th>Spend</th><th>Revenue</th><th>ROAS</th><th>Conv.</th></tr></thead><tbody>';
                    active.slice(0, 20).forEach(function(c) {
                        var cr = c.roas || 0;
                        html += '<tr><td>' + (c.name||'--') + '</td><td><span class="status status-' + c.status + '">' + c.status + '</span></td><td>$' + (c.daily_budget||0).toFixed(2) + '</td><td>$' + (c.spend||0).toFixed(2) + '</td><td>$' + (c.revenue||0).toFixed(2) + '</td><td class="' + (cr>=2?'positive':cr>=1?'warning':'') + '">' + cr.toFixed(2) + 'x</td><td>' + (c.conversions||0) + '</td></tr>';
                    });
                    if (active.length > 20) html += '<tr><td colspan="7" style="text-align:center;color:#9ca3af;font-style:italic">+ ' + (active.length-20) + ' more campaigns</td></tr>';
                    html += '</tbody></table>';
                } else {
                    html += '<div class="no-data">No active Google Ads campaigns. Campaigns will appear here once pushed to Google Ads.</div>';
                }
                body.innerHTML = html;
            } catch(e) {
                body.innerHTML = '<div class="no-data">Failed to load Google Ads data: ' + e.message + '</div>';
            }
        }
        async function loadActivity() {
            const container = document.getElementById('activity-log');
            try {
                const res = await fetch(`${API}/dashboard/activity?limit=10`);
                const logs = await res.json();
                if (!logs || logs.length === 0) {
                    container.innerHTML = '<div class="no-data">No activity recorded yet. Actions will appear here once the automation engine runs.</div>';
                    return;
                }
                container.innerHTML = logs.map(function(l) {
                    var time = l.timestamp ? new Date(l.timestamp).toLocaleString() : '--';
                    return '<div class="activity-item"><div class="activity-time">' + time + '</div><div class="activity-desc"><strong>' + (l.action||'') + '</strong>: ' + (l.details||l.entity_type||'') + ' ' + (l.entity_id||'') + '</div></div>';
                }).join('');
            } catch(e) {
                container.innerHTML = '<div class="no-data">Failed to load activity log</div>';
            }
        }
        async function pauseAll() {
            if (!confirm('Pause ALL campaigns? This is an emergency action.')) return;
            try {
                const res = await fetch(`${API}/dashboard/pause-all`, { method: 'POST' });
                const d = await res.json();
                alert('Paused ' + d.campaigns_paused + ' campaigns');
                refreshAll();
            } catch(e) { alert('Failed: ' + e.message); }
        }
        function viewReports() { window.open('/docs', '_blank'); }
        async function syncProducts() {
            try {
                const res = await fetch(`${API}/products/sync-shopify`, { method: 'POST' });
                const d = await res.json();
                alert('Synced ' + (d.synced||d.products_synced||0) + ' products');
            } catch(e) { alert('Sync failed: ' + e.message); }
        }
        function refreshAll() { hideError(); loadDashboardStatus(); loadMetaPerformance(); loadGooglePerformance(); loadActivity(); }
        refreshAll();
        setInterval(refreshAll, 60000);
    </script>
</body>
</html>'''


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
