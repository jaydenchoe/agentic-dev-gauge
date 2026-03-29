"""Tests for MonitorService and UsageService."""

import pytest
from datetime import datetime, timezone

from src.core.models import TokenUsage
from src.services.monitor_service import MonitorService
from src.services.usage_service import UsageService
from tests.conftest import MockMetricsAdapter, MockUsageAdapter


class TestMonitorService:
    @pytest.mark.asyncio
    async def test_collect_once(self, mock_metrics):
        svc = MonitorService(mock_metrics, interval=1.0)
        snapshot = await svc.collect_once()

        assert snapshot is not None
        assert snapshot.cpu.usage_percent == 45.0
        assert snapshot.memory.usage_percent == 62.5
        assert svc.latest is snapshot

    @pytest.mark.asyncio
    async def test_history_accumulates(self, mock_metrics):
        svc = MonitorService(mock_metrics, interval=1.0)
        await svc.collect_once()
        await svc.collect_once()

        assert len(svc.history) == 2

    @pytest.mark.asyncio
    async def test_latest_is_none_initially(self, mock_metrics):
        svc = MonitorService(mock_metrics)
        assert svc.latest is None


class TestUsageService:
    @pytest.mark.asyncio
    async def test_collect_once_with_key(self):
        adapter = MockUsageAdapter(provider="anthropic")
        svc = UsageService(
            adapters=[adapter],
            api_keys={"anthropic": "test-key"},
            interval=60.0,
        )
        snapshot = await svc.collect_once()

        assert snapshot is not None
        assert len(snapshot.usages) == 1
        assert snapshot.usages[0].provider == "anthropic"
        assert snapshot.usages[0].total_tokens == 1500
        assert snapshot.total_cost_usd == 0.05

    @pytest.mark.asyncio
    async def test_skip_provider_without_key(self):
        adapter = MockUsageAdapter(provider="openai")
        svc = UsageService(
            adapters=[adapter],
            api_keys={},  # no keys
            interval=60.0,
        )
        snapshot = await svc.collect_once()

        assert len(snapshot.usages) == 0

    @pytest.mark.asyncio
    async def test_multiple_providers(self):
        adapters = [
            MockUsageAdapter(provider="anthropic"),
            MockUsageAdapter(provider="openai"),
        ]
        svc = UsageService(
            adapters=adapters,
            api_keys={"anthropic": "key1", "openai": "key2"},
        )
        snapshot = await svc.collect_once()

        assert len(snapshot.usages) == 2
        providers = {u.provider for u in snapshot.usages}
        assert providers == {"anthropic", "openai"}

    @pytest.mark.asyncio
    async def test_total_cost_none_when_all_none(self):
        adapter = MockUsageAdapter(
            provider="openai",
            usages=[TokenUsage(
                provider="openai", model="gpt-4", input_tokens=100,
                output_tokens=50, total_tokens=150, cost_usd=None,
            )],
        )
        svc = UsageService(
            adapters=[adapter],
            api_keys={"openai": "key"},
        )
        snapshot = await svc.collect_once()
        assert snapshot.total_cost_usd is None
