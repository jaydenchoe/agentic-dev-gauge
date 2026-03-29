"""Tests for AlertService — threshold detection and notification."""

import pytest
from datetime import datetime, timezone

from src.core.models import ThresholdConfig, UsageSnapshot, TokenUsage
from src.services.alert_service import AlertService
from tests.conftest import MockNotifier, make_snapshot


@pytest.fixture
def alert_svc(default_thresholds, mock_notifier):
    return AlertService(default_thresholds, mock_notifier)


@pytest.fixture
def notifier():
    return MockNotifier()


# ---------------------------------------------------------------------------
# System threshold tests
# ---------------------------------------------------------------------------

class TestCheckSystem:
    @pytest.mark.asyncio
    async def test_no_alert_below_warning(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=50.0, memory_percent=60.0)
        alerts = await alert_svc.check_system(snapshot)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_warning_at_threshold(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=80.0)
        alerts = await alert_svc.check_system(snapshot)
        assert len(alerts) == 1
        assert alerts[0].level == "warning"
        assert alerts[0].metric == "cpu_percent"
        assert alerts[0].current_value == 80.0
        assert alerts[0].threshold == 80

    @pytest.mark.asyncio
    async def test_critical_at_threshold(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=95.0)
        alerts = await alert_svc.check_system(snapshot)
        assert len(alerts) == 1
        assert alerts[0].level == "critical"
        assert alerts[0].metric == "cpu_percent"

    @pytest.mark.asyncio
    async def test_multiple_alerts(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=90.0, memory_percent=85.0)
        alerts = await alert_svc.check_system(snapshot)
        metrics = {a.metric for a in alerts}
        assert "cpu_percent" in metrics
        assert "memory_percent" in metrics

    @pytest.mark.asyncio
    async def test_cooldown_suppresses_repeat(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=90.0)
        first = await alert_svc.check_system(snapshot)
        assert len(first) == 1

        second = await alert_svc.check_system(snapshot)
        assert len(second) == 0  # suppressed by cooldown

    @pytest.mark.asyncio
    async def test_recent_alerts_stored(self, alert_svc):
        snapshot = make_snapshot(cpu_percent=90.0)
        await alert_svc.check_system(snapshot)
        assert len(alert_svc.recent_alerts) == 1


# ---------------------------------------------------------------------------
# Usage threshold tests
# ---------------------------------------------------------------------------

class TestCheckUsage:
    @pytest.mark.asyncio
    async def test_no_alert_below_cost_threshold(self, alert_svc):
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=[],
            total_cost_usd=5.0,
        )
        alerts = await alert_svc.check_usage(snapshot)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_warning_on_cost(self, alert_svc):
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=[],
            total_cost_usd=15.0,
        )
        alerts = await alert_svc.check_usage(snapshot)
        assert len(alerts) == 1
        assert alerts[0].level == "warning"
        assert alerts[0].metric == "token_cost"

    @pytest.mark.asyncio
    async def test_critical_on_cost(self, alert_svc):
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=[],
            total_cost_usd=55.0,
        )
        alerts = await alert_svc.check_usage(snapshot)
        assert len(alerts) == 1
        assert alerts[0].level == "critical"

    @pytest.mark.asyncio
    async def test_no_alert_when_cost_is_none(self, alert_svc):
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=[],
            total_cost_usd=None,
        )
        alerts = await alert_svc.check_usage(snapshot)
        assert alerts == []


# ---------------------------------------------------------------------------
# Notification tests
# ---------------------------------------------------------------------------

class TestNotification:
    @pytest.mark.asyncio
    async def test_notifier_called_on_alert(self, default_thresholds):
        notifier = MockNotifier()
        svc = AlertService(default_thresholds, notifier)
        snapshot = make_snapshot(cpu_percent=90.0)
        await svc.check_system(snapshot)
        # Notification is fire-and-forget via asyncio.create_task,
        # give it a chance to execute
        import asyncio
        await asyncio.sleep(0.05)
        assert len(notifier.sent_alerts) == 1
        assert notifier.sent_alerts[0].metric == "cpu_percent"

    @pytest.mark.asyncio
    async def test_no_notifier_ok(self, default_thresholds):
        svc = AlertService(default_thresholds, notifier=None)
        snapshot = make_snapshot(cpu_percent=90.0)
        alerts = await svc.check_system(snapshot)
        assert len(alerts) == 1  # still generates alert, just no notification


# ---------------------------------------------------------------------------
# Threshold update tests
# ---------------------------------------------------------------------------

class TestUpdateThresholds:
    @pytest.mark.asyncio
    async def test_update_thresholds(self, alert_svc):
        new_thresholds = [
            ThresholdConfig(metric="cpu_percent", warning=50, critical=70),
        ]
        alert_svc.update_thresholds(new_thresholds)
        snapshot = make_snapshot(cpu_percent=55.0)
        alerts = await alert_svc.check_system(snapshot)
        assert len(alerts) == 1
        assert alerts[0].level == "warning"
