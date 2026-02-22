"""Tests for Meta Ads router — campaign list, performance, A/B testing."""


class TestMetaCampaigns:
    def test_list_campaigns(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/campaigns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "campaigns" in data
        assert data["count"] >= 0

    def test_status_check(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "connected" in data

    def test_activate_campaign(self, client, mock_meta_api):
        resp = client.post(
            "/api/v1/meta/activate-campaign",
            json={"campaign_id": "120206746647300364"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "activated"

    def test_pause_campaign(self, client, mock_meta_api):
        resp = client.post(
            "/api/v1/meta/pause-campaign",
            json={"campaign_id": "120206746647300364"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"

    def test_set_budget(self, client, mock_meta_api):
        resp = client.post(
            "/api/v1/meta/set-budget",
            json={"campaign_id": "120206746647300364", "daily_budget_cents": 2500},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["budget_dollars"] == 25.0


class TestMetaPerformance:
    def test_campaign_recommendations(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/campaign-recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "recommendations" in data
        assert "campaigns" in data

    def test_capi_status(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/capi-status")
        assert resp.status_code == 200

    def test_ad_images_list(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/ad-images")
        assert resp.status_code == 200


class TestMetaAdCRUD:
    def test_create_ad(self, client, mock_meta_api):
        resp = client.post(
            "/api/v1/meta/create-ad",
            json={
                "adset_id": "adset_123",
                "name": "Test Ad",
                "primary_text": "Buy now",
                "headline": "Great Deal",
                "description": "Limited time offer",
                "link": "https://court-sportswear.com",
                "image_url": "https://example.com/img.jpg",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"

    def test_delete_ad(self, client, mock_external_apis):
        resp = client.delete("/api/v1/meta/ads/ad_123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"


class TestABTesting:
    def test_no_running_tests(self, client, mock_meta_api):
        resp = client.get("/api/v1/meta/test-results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # When no tests, response has "message" and empty tests list
        assert data.get("tests_analyzed", 0) == 0 or "No running" in data.get("message", "")

    def test_auto_optimize_empty(self, client, mock_meta_api):
        resp = client.post("/api/v1/meta/auto-optimize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["optimized_count"] == 0

    def test_create_test_validates_variant_type(self, client, mock_meta_api):
        resp = client.post(
            "/api/v1/meta/create-test",
            json={
                "original_ad_id": "ad_123",
                "variant_type": "invalid_type",
                "variant_value": "test",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "variant_type" in data["message"]
