"""Tests for adapter implementations."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.core.models import SystemSnapshot, TokenUsage


# ---------------------------------------------------------------------------
# Psutil adapter
# ---------------------------------------------------------------------------

class TestPsutilAdapter:
    @pytest.mark.asyncio
    async def test_is_available(self):
        from src.adapters.system.psutil_adapter import PsutilMetricsAdapter
        adapter = PsutilMetricsAdapter()
        assert await adapter.is_available() is True

    @pytest.mark.asyncio
    async def test_collect_returns_snapshot(self):
        from src.adapters.system.psutil_adapter import PsutilMetricsAdapter
        adapter = PsutilMetricsAdapter()
        snapshot = await adapter.collect()

        assert isinstance(snapshot, SystemSnapshot)
        assert 0 <= snapshot.cpu.usage_percent <= 100
        assert snapshot.memory.total_gb > 0
        assert snapshot.memory.usage_percent >= 0
        assert snapshot.disk.total_gb > 0
        assert snapshot.network.bytes_sent_per_sec >= 0
        assert snapshot.network.bytes_recv_per_sec >= 0
        assert snapshot.gpu is None  # psutil doesn't provide GPU

    @pytest.mark.asyncio
    async def test_cpu_per_core_populated(self):
        from src.adapters.system.psutil_adapter import PsutilMetricsAdapter
        adapter = PsutilMetricsAdapter()
        snapshot = await adapter.collect()

        assert len(snapshot.cpu.per_core) > 0
        for core_pct in snapshot.cpu.per_core:
            assert 0 <= core_pct <= 100

    @pytest.mark.asyncio
    async def test_network_delta_clamps_negative_and_computes_rate(self):
        import time
        from types import SimpleNamespace
        from src.adapters.system.psutil_adapter import PsutilMetricsAdapter

        adapter = PsutilMetricsAdapter()
        adapter._prev_net = SimpleNamespace(bytes_sent=1000, bytes_recv=2000)
        adapter._prev_ts = time.monotonic() - 1.0

        with patch(
            "src.adapters.system.psutil_adapter.psutil.net_io_counters",
            return_value=SimpleNamespace(bytes_sent=3000, bytes_recv=5000),
        ):
            network = adapter._network(1.0)

        assert network.bytes_sent_per_sec == pytest.approx(2000, rel=0.1)
        assert network.bytes_recv_per_sec == pytest.approx(3000, rel=0.1)

        with patch(
            "src.adapters.system.psutil_adapter.psutil.net_io_counters",
            return_value=SimpleNamespace(bytes_sent=100, bytes_recv=200),
        ):
            network = adapter._network(1.0)

        assert network.bytes_sent_per_sec == 0
        assert network.bytes_recv_per_sec == 0


# ---------------------------------------------------------------------------
# Anthropic adapter (mock HTTP)
# ---------------------------------------------------------------------------

class TestAnthropicAdapter:
    @pytest.mark.asyncio
    async def test_parse_usage_data(self):
        """Test with the real API response structure: data[].results[]."""
        from unittest.mock import AsyncMock, patch
        from src.adapters.ai_usage.anthropic_adapter import AnthropicUsageAdapter

        # Simulate paginated API response with daily buckets
        mock_response_data = {
            "data": [
                {
                    "starting_at": "2026-03-01T00:00:00Z",
                    "ending_at": "2026-03-02T00:00:00Z",
                    "results": [
                        {"model": "claude-sonnet-4-6", "input_tokens": 10000, "output_tokens": 5000},
                    ],
                },
                {
                    "starting_at": "2026-03-02T00:00:00Z",
                    "ending_at": "2026-03-03T00:00:00Z",
                    "results": [
                        {"model": "claude-sonnet-4-6", "input_tokens": 20000, "output_tokens": 10000},
                        {"model": "claude-haiku-4-5-20251001", "input_tokens": 5000, "output_tokens": 2000},
                    ],
                },
            ],
            "has_more": False,
        }

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: mock_response_data
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        adapter = AnthropicUsageAdapter()
        with patch("src.adapters.ai_usage.anthropic_adapter.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_usage("sk-ant-admin01-test")

        assert isinstance(result, list)
        assert len(result) == 2  # two unique models

        sonnet = next(u for u in result if "sonnet" in u.model)
        assert sonnet.input_tokens == 30000
        assert sonnet.output_tokens == 15000
        assert sonnet.total_tokens == 45000
        assert sonnet.provider == "anthropic"
        assert isinstance(sonnet, TokenUsage)

    @pytest.mark.asyncio
    async def test_empty_data(self):
        from unittest.mock import AsyncMock, patch
        from src.adapters.ai_usage.anthropic_adapter import AnthropicUsageAdapter, _usage_cache
        _usage_cache.clear()

        mock_resp = AsyncMock()
        mock_resp.json = lambda: {"data": [{"results": []}], "has_more": False}
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        adapter = AnthropicUsageAdapter()
        with patch("src.adapters.ai_usage.anthropic_adapter.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_usage("sk-ant-admin01-test")
        assert result == []


# ---------------------------------------------------------------------------
# OpenAI adapter (mock HTTP)
# ---------------------------------------------------------------------------

class TestOpenAIAdapter:
    @pytest.mark.asyncio
    async def test_parse_usage_data(self):
        from src.adapters.ai_usage.openai_adapter import OpenAIUsageAdapter

        adapter = OpenAIUsageAdapter()
        mock_data = {
            "data": [
                {"result": {"model": "gpt-4", "input_tokens": 5000, "output_tokens": 2000}},
                {"result": {"model": "gpt-4", "input_tokens": 3000, "output_tokens": 1000}},
            ]
        }
        result = adapter._parse(mock_data)

        assert len(result) == 1
        assert result[0].provider == "openai"
        assert result[0].input_tokens == 8000
        assert result[0].output_tokens == 3000


# ---------------------------------------------------------------------------
# Notification adapter (mock HTTP)
# ---------------------------------------------------------------------------

class TestOpenClawNotifier:
    @pytest.mark.asyncio
    async def test_send_alert_success(self):
        from src.adapters.notification.openclaw_notifier import OpenClawNotifier
        from src.core.models import AlertEvent
        from datetime import datetime, timezone

        notifier = OpenClawNotifier(
            gateway_url="https://example.com",
            api_key="test-key",
        )
        event = AlertEvent(
            timestamp=datetime.now(timezone.utc),
            metric="cpu_percent",
            current_value=95.0,
            threshold=90.0,
            level="critical",
            message="CPU high",
        )

        with patch("src.adapters.notification.openclaw_notifier.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await notifier.send_alert(event)
            assert result is True
            mock_client.post.assert_called_once()

            # Verify URL includes /api/sessions/main/messages
            call_args = mock_client.post.call_args
            assert "/api/sessions/main/messages" in call_args[0][0]
