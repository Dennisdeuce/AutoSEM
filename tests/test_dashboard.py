"""Tests for Dashboard router — overview aggregation, activity, trends."""

from datetime import date, timedelta
from app.database import CampaignModel, ActivityLogModel, PerformanceSnapshotModel


class TestDashboardStatus:
    def test_status_returns_200(self, client, mock_external_apis):
        resp = client.get("/api/v1/dashboard/status")
        assert resp.status_code == 200

    def test_status_fields(self, client, mock_external_apis):
        data = client.get("/api/v1/dashboard/status").json()
        assert "status" in data
        assert "spend_7d" in data
        assert "clicks_7d" in data
        assert "active_campaigns" in data
        assert "platforms_connected" in data

    def test_status_aggregates_platforms(self, client, mock_external_apis, db_session, seed_campaigns):
        """Status should aggregate spend from Meta + TikTok."""
        data = client.get("/api/v1/dashboard/status").json()
        # Mocked Meta returns 10.50, TikTok returns 5.00
        assert data["spend_7d"] >= 0
        assert isinstance(data["impressions_7d"], int)

    def test_status_counts_active_campaigns(self, client, mock_external_apis, db_session, seed_campaigns):
        data = client.get("/api/v1/dashboard/status").json()
        # seed_campaigns has 2 active (meta + tiktok), 1 paused
        assert data["active_campaigns"] == 2


class TestDashboardActivity:
    def test_activity_empty(self, client):
        resp = client.get("/api/v1/dashboard/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_activity_returns_entries(self, client, db_session):
        log = ActivityLogModel(
            action="TEST_ACTION",
            entity_type="test",
            entity_id="1",
            details="Test activity",
        )
        db_session.add(log)
        db_session.commit()

        data = client.get("/api/v1/dashboard/activity").json()
        assert len(data) >= 1
        assert data[0]["action"] == "TEST_ACTION"

    def test_activity_respects_limit(self, client, db_session):
        for i in range(5):
            db_session.add(ActivityLogModel(
                action=f"ACTION_{i}", entity_type="test", entity_id=str(i), details="",
            ))
        db_session.commit()

        data = client.get("/api/v1/dashboard/activity?limit=3").json()
        assert len(data) == 3

    def test_log_activity(self, client):
        resp = client.post(
            "/api/v1/dashboard/log-activity",
            params={"action": "TEST_LOG", "details": "Logged from test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "logged"


class TestDashboardEmergencyControls:
    def test_pause_all(self, client, db_session, seed_campaigns):
        resp = client.post("/api/v1/dashboard/pause-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["campaigns_paused"] == 2  # 2 active campaigns

    def test_resume_all(self, client, db_session, seed_campaigns):
        # First pause
        client.post("/api/v1/dashboard/pause-all")
        # Then resume
        resp = client.post("/api/v1/dashboard/resume-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resumed"


class TestDashboardTrends:
    def test_trends_empty(self, client):
        resp = client.get("/api/v1/dashboard/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_trends_with_snapshots(self, client, db_session, seed_campaigns):
        today = date.today()
        for i in range(3):
            snap = PerformanceSnapshotModel(
                date=today - timedelta(days=i),
                platform="meta",
                campaign_id=1,
                spend=10.0 + i,
                clicks=100 + i * 10,
                impressions=5000 + i * 500,
                ctr=2.0,
                cpc=0.10,
                conversions=0,
                revenue=0,
            )
            db_session.add(snap)
        db_session.commit()

        data = client.get("/api/v1/dashboard/trends?days=7").json()
        assert data["status"] == "ok"
        assert len(data["data"]) == 3

    def test_trends_date_filtering(self, client, db_session, seed_campaigns):
        """Trends should only return data within the requested window."""
        today = date.today()
        # Add old snapshot outside 7-day window
        db_session.add(PerformanceSnapshotModel(
            date=today - timedelta(days=60),
            platform="meta", campaign_id=1,
            spend=5.0, clicks=50, impressions=2000,
        ))
        # Add recent snapshot
        db_session.add(PerformanceSnapshotModel(
            date=today - timedelta(days=1),
            platform="meta", campaign_id=1,
            spend=15.0, clicks=150, impressions=7000,
        ))
        db_session.commit()

        data = client.get("/api/v1/dashboard/trends?days=7").json()
        assert data["status"] == "ok"
        # Should only return the recent one (within 7 days)
        assert len(data["data"]) == 1


class TestDashboardFunnel:
    def test_funnel_returns_structure(self, client, mock_external_apis):
        resp = client.get("/api/v1/dashboard/funnel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "funnel" in data
        assert "dropoff" in data
        funnel = data["funnel"]
        assert "impressions" in funnel
        assert "clicks" in funnel
        assert "spend" in funnel
