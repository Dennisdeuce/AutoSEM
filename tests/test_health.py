"""Tests for health endpoints and core app functionality."""

from app.version import VERSION


class TestRootEndpoint:
    def test_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_contains_version(self, client):
        data = client.get("/").json()
        assert data["version"] == VERSION

    def test_root_shows_status_running(self, client):
        data = client.get("/").json()
        assert data["status"] == "running"

    def test_root_lists_routers(self, client):
        data = client.get("/").json()
        assert isinstance(data["routers"], list)
        assert len(data["routers"]) > 0


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_reports_healthy(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"

    def test_health_includes_version(self, client):
        data = client.get("/health").json()
        assert data["version"] == VERSION

    def test_health_lists_loaded_routers(self, client):
        data = client.get("/health").json()
        assert "routers_loaded" in data
        assert isinstance(data["routers_loaded"], list)
        assert data["router_count"] == len(data["routers_loaded"])


class TestVersionEndpoint:
    def test_version_returns_200(self, client):
        resp = client.get("/version")
        assert resp.status_code == 200

    def test_version_matches(self, client):
        data = client.get("/version").json()
        assert data["version"] == VERSION


class TestRouterRegistration:
    """Verify critical routers respond (don't 404)."""

    def test_dashboard_status(self, client, mock_external_apis):
        resp = client.get("/api/v1/dashboard/status")
        assert resp.status_code == 200

    def test_meta_status(self, client, mock_external_apis):
        resp = client.get("/api/v1/meta/status")
        assert resp.status_code == 200

    def test_health_deep(self, client):
        resp = client.get("/api/v1/health/deep")
        assert resp.status_code == 200

    def test_health_env_check(self, client):
        resp = client.get("/api/v1/health/env-check")
        assert resp.status_code == 200
        data = resp.json()
        assert "env_vars" in data

    def test_campaigns_list(self, client):
        resp = client.get("/api/v1/campaigns/active")
        # Should return 200 even with empty DB
        assert resp.status_code == 200

    def test_settings_get(self, client):
        resp = client.get("/api/v1/settings/")
        assert resp.status_code == 200

    def test_seo_jsonld(self, client):
        resp = client.get("/api/v1/seo/all-jsonld")
        assert resp.status_code == 200
