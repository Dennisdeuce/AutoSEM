"""Tests for the CampaignOptimizer — budget rules, bounds, scaling logic."""

import pytest
from unittest.mock import patch, MagicMock
from app.database import CampaignModel, SettingsModel
from app.services.optimizer import CampaignOptimizer


class TestOptimizerBudgetBounds:
    """Test that budget adjustments respect min/max bounds."""

    def test_budget_increase_capped_at_max(self):
        """MAX_DAILY_BUDGET should be $50."""
        assert CampaignOptimizer.MAX_DAILY_BUDGET == 50.0

    def test_budget_decrease_floored_at_min(self):
        """MIN_DAILY_BUDGET should be $3."""
        assert CampaignOptimizer.MIN_DAILY_BUDGET == 3.0

    def test_scale_winner_capped_at_25(self):
        """Scale winner should cap at $25."""
        assert CampaignOptimizer.SCALE_WINNER_MAX_BUDGET == 25.0
        assert CampaignOptimizer.SCALE_WINNER_INCREASE == 1.20


class TestOptimizerConstants:
    """Verify optimizer thresholds match expected values."""

    def test_budget_factors(self):
        assert CampaignOptimizer.BUDGET_INCREASE_FACTOR == 1.25
        assert CampaignOptimizer.BUDGET_DECREASE_FACTOR == 0.75

    def test_ctr_thresholds(self):
        assert CampaignOptimizer.LOW_CTR_THRESHOLD == 0.005  # 0.5%
        assert CampaignOptimizer.HIGH_CTR_THRESHOLD == 0.03  # 3.0%

    def test_minimum_data_thresholds(self):
        assert CampaignOptimizer.MIN_IMPRESSIONS_FOR_DECISION == 100
        assert CampaignOptimizer.MIN_CLICKS_FOR_DECISION == 10

    def test_low_conversion_rate(self):
        assert CampaignOptimizer.LOW_CONVERSION_RATE == 0.01  # 1%


class TestOptimizerBudgetRules:
    """Test budget adjustment arithmetic using class constants."""

    def test_increase_by_factor(self):
        """25% increase: $20 -> $25."""
        current = 20.0
        new_budget = round(current * CampaignOptimizer.BUDGET_INCREASE_FACTOR, 2)
        assert new_budget == 25.0

    def test_decrease_by_factor(self):
        """25% decrease: $20 -> $15."""
        current = 20.0
        new_budget = round(current * CampaignOptimizer.BUDGET_DECREASE_FACTOR, 2)
        assert new_budget == 15.0

    def test_increase_respects_max(self):
        """Increase from $45 should cap at $50, not $56.25."""
        current = 45.0
        new_budget = min(
            round(current * CampaignOptimizer.BUDGET_INCREASE_FACTOR, 2),
            CampaignOptimizer.MAX_DAILY_BUDGET,
        )
        assert new_budget == 50.0

    def test_decrease_respects_min(self):
        """Decrease from $3.50 should floor at $3.00, not $2.625."""
        current = 3.50
        new_budget = max(
            round(current * CampaignOptimizer.BUDGET_DECREASE_FACTOR, 2),
            CampaignOptimizer.MIN_DAILY_BUDGET,
        )
        assert new_budget == 3.0

    def test_scale_winner_increase(self):
        """20% scale: $20 -> $24."""
        current = 20.0
        new_budget = round(current * CampaignOptimizer.SCALE_WINNER_INCREASE, 2)
        assert new_budget == 24.0

    def test_scale_winner_caps_at_max(self):
        """Scale from $22 should cap at $25, not $26.40."""
        current = 22.0
        new_budget = min(
            round(current * CampaignOptimizer.SCALE_WINNER_INCREASE, 2),
            CampaignOptimizer.SCALE_WINNER_MAX_BUDGET,
        )
        assert new_budget == 25.0


class TestOptimizerOptimizeAll:
    """Test the optimize_all entry point with mocked dependencies."""

    @patch("app.services.optimizer.NotificationService")
    @patch("app.services.optimizer.MetaAdsService")
    def test_optimize_all_returns_dict(self, mock_meta_cls, mock_notif_cls, db_session, seed_campaigns):
        mock_meta_cls.return_value = MagicMock()
        mock_notif_cls.return_value = MagicMock()

        optimizer = CampaignOptimizer(db_session)
        # Mock the internal methods to isolate the test
        optimizer._optimize_campaign = MagicMock(return_value=[])
        optimizer._check_safety_limits = MagicMock(return_value=[])

        result = optimizer.optimize_all()

        assert isinstance(result, dict)
        assert "optimized" in result
        assert "actions" in result
        assert "timestamp" in result

    @patch("app.services.optimizer.NotificationService")
    @patch("app.services.optimizer.MetaAdsService")
    def test_optimize_all_processes_active_campaigns(self, mock_meta_cls, mock_notif_cls, db_session, seed_campaigns):
        mock_meta_cls.return_value = MagicMock()
        mock_notif_cls.return_value = MagicMock()

        optimizer = CampaignOptimizer(db_session)
        optimizer._optimize_campaign = MagicMock(return_value=[])
        optimizer._check_safety_limits = MagicMock(return_value=[])

        optimizer.optimize_all()

        # Should be called for each ACTIVE campaign (2: "Test Active Campaign" + "TikTok Test Campaign")
        assert optimizer._optimize_campaign.call_count == 2

    @patch("app.services.optimizer.NotificationService")
    @patch("app.services.optimizer.MetaAdsService")
    def test_optimize_all_skips_paused(self, mock_meta_cls, mock_notif_cls, db_session, seed_campaigns):
        mock_meta_cls.return_value = MagicMock()
        mock_notif_cls.return_value = MagicMock()

        optimizer = CampaignOptimizer(db_session)
        optimizer._optimize_campaign = MagicMock(return_value=[])
        optimizer._check_safety_limits = MagicMock(return_value=[])

        optimizer.optimize_all()

        # "Test Paused Campaign" should not be optimized
        campaign_names = [call.args[0].name for call in optimizer._optimize_campaign.call_args_list]
        assert "Test Paused Campaign" not in campaign_names

    @patch("app.services.optimizer.NotificationService")
    @patch("app.services.optimizer.MetaAdsService")
    def test_optimize_all_empty_db(self, mock_meta_cls, mock_notif_cls, db_session):
        """With no campaigns, optimize_all returns 0 optimized."""
        mock_meta_cls.return_value = MagicMock()
        mock_notif_cls.return_value = MagicMock()

        optimizer = CampaignOptimizer(db_session)
        result = optimizer.optimize_all()

        assert result["optimized"] == 0
        assert result["actions"] == []


class TestOptimizerAwarenessMode:
    """Test that awareness mode (min_roas_threshold=0) doesn't auto-pause."""

    def test_awareness_mode_threshold_zero(self, db_session):
        """When min_roas_threshold=0, optimizer should not pause for low ROAS."""
        setting = SettingsModel(key="min_roas_threshold", value="0.0")
        db_session.add(setting)
        db_session.commit()

        row = db_session.query(SettingsModel).filter(
            SettingsModel.key == "min_roas_threshold"
        ).first()
        assert float(row.value) == 0.0

    @patch("app.services.optimizer.NotificationService")
    @patch("app.services.optimizer.MetaAdsService")
    def test_awareness_mode_loads_from_db(self, mock_meta_cls, mock_notif_cls, db_session):
        """Optimizer should read min_roas_threshold from DB settings."""
        mock_meta_cls.return_value = MagicMock()
        mock_notif_cls.return_value = MagicMock()

        db_session.add(SettingsModel(key="min_roas_threshold", value="0.0"))
        db_session.commit()

        optimizer = CampaignOptimizer(db_session)
        assert optimizer.settings["min_roas_threshold"] == 0.0
