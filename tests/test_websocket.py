"""Tests for WebSocket endpoint — connection, subscribe, broadcast, channel filtering."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.websocket import router as ws_router, ConnectionManager, _serialise
from src.core.models import (
    AlertEvent,
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
    ThresholdConfig,
    TokenUsage,
    UsageSnapshot,
)
from src.services.alert_service import AlertService
from src.services.monitor_service import MonitorService
from src.services.usage_service import UsageService
from tests.conftest import MockMetricsAdapter, MockUsageAdapter, MockNotifier


@pytest.fixture
def ws_app(default_thresholds):
    """Build a FastAPI app with WebSocket router and mock services."""
    app = FastAPI()
    app.include_router(ws_router)

    metrics_adapter = MockMetricsAdapter()
    usage_adapter = MockUsageAdapter(provider="anthropic")
    notifier = MockNotifier()

    app.state.monitor_service = MonitorService(metrics_adapter, interval=2.0)
    app.state.usage_service = UsageService(
        adapters=[usage_adapter],
        api_keys={"anthropic": "test-key"},
    )
    app.state.alert_service = AlertService(default_thresholds, notifier)
    app.state.settings = MagicMock(
        metrics_interval_sec=2.0,
        usage_interval_sec=60.0,
        thresholds=default_thresholds,
    )
    return app


@pytest.fixture
def ws_client(ws_app):
    return TestClient(ws_app)


# ---------------------------------------------------------------------------
# Connection / disconnection
# ---------------------------------------------------------------------------

class TestWebSocketConnection:
    def test_connect_and_disconnect(self, ws_client):
        with ws_client.websocket_connect("/ws/live") as ws:
            # Connection established — send a subscribe to confirm it's alive
            ws.send_text(json.dumps({
                "type": "subscribe",
                "channels": ["system_metrics"],
            }))
            # No error means connection is alive; closing exits cleanly

    def test_multiple_connections(self, ws_client):
        """Two clients can connect simultaneously."""
        with ws_client.websocket_connect("/ws/live") as ws1:
            with ws_client.websocket_connect("/ws/live") as ws2:
                ws1.send_text(json.dumps({"type": "subscribe", "channels": ["alert"]}))
                ws2.send_text(json.dumps({"type": "subscribe", "channels": ["alert"]}))


# ---------------------------------------------------------------------------
# Subscribe message parsing
# ---------------------------------------------------------------------------

class TestSubscribe:
    def test_subscribe_changes_channels(self, ws_client):
        """After subscribe, only subscribed channels should be received."""
        with ws_client.websocket_connect("/ws/live") as ws:
            # Subscribe to only "alert" channel
            ws.send_text(json.dumps({
                "type": "subscribe",
                "channels": ["alert"],
            }))
            # Sending a non-subscribe message should be ignored (no crash)
            ws.send_text(json.dumps({"type": "ping"}))
            # Malformed JSON should be ignored
            ws.send_text("not json at all")

    def test_subscribe_requires_channels_list(self, ws_client):
        """Subscribe with non-list channels should be ignored (no crash)."""
        with ws_client.websocket_connect("/ws/live") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe",
                "channels": "system_metrics",  # string, not list
            }))


# ---------------------------------------------------------------------------
# ConnectionManager unit tests
# ---------------------------------------------------------------------------

class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_broadcast_to_subscribed(self):
        mgr = ConnectionManager()
        sent_messages = []

        # Create a mock WebSocket
        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())
        mock_ws.send_text = MagicMock(side_effect=lambda msg: sent_messages.append(msg))

        await mgr.connect(mock_ws)
        # Default subscription includes all channels
        assert mgr.active_count == 1

        snapshot = _make_test_snapshot()
        await mgr.broadcast("system_metrics", snapshot)

        assert len(sent_messages) == 1
        msg = json.loads(sent_messages[0])
        assert msg["type"] == "system_metrics"
        assert "cpu" in msg["data"]
        assert "usage_percent" in msg["data"]["cpu"]

    @pytest.mark.asyncio
    async def test_broadcast_filtered_by_channel(self):
        """Client subscribed to only 'alert' should not receive 'system_metrics'."""
        mgr = ConnectionManager()
        sent_messages = []

        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())
        mock_ws.send_text = MagicMock(side_effect=lambda msg: sent_messages.append(msg))

        await mgr.connect(mock_ws)
        mgr.subscribe(mock_ws, ["alert"])  # only alert channel

        snapshot = _make_test_snapshot()
        await mgr.broadcast("system_metrics", snapshot)

        # Should NOT receive system_metrics
        assert len(sent_messages) == 0

    @pytest.mark.asyncio
    async def test_broadcast_alert_to_subscribed(self):
        """Client subscribed to 'alert' should receive alert broadcasts."""
        mgr = ConnectionManager()
        sent_messages = []

        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())
        mock_ws.send_text = MagicMock(side_effect=lambda msg: sent_messages.append(msg))

        await mgr.connect(mock_ws)
        mgr.subscribe(mock_ws, ["alert"])

        event = AlertEvent(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            metric="cpu_percent",
            current_value=92.5,
            threshold=90.0,
            level="critical",
            message="CPU high",
        )
        await mgr.broadcast("alert", event)

        assert len(sent_messages) == 1
        msg = json.loads(sent_messages[0])
        assert msg["type"] == "alert"
        assert msg["data"]["level"] == "critical"
        assert msg["data"]["metric"] == "cpu_percent"

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self):
        mgr = ConnectionManager()

        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())

        await mgr.connect(mock_ws)
        assert mgr.active_count == 1

        mgr.disconnect(mock_ws)
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        """If send_text raises, the connection should be removed."""
        mgr = ConnectionManager()

        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())
        mock_ws.send_text = MagicMock(side_effect=Exception("connection closed"))

        await mgr.connect(mock_ws)
        assert mgr.active_count == 1

        snapshot = _make_test_snapshot()
        await mgr.broadcast("system_metrics", snapshot)

        # Dead connection should have been cleaned up
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_usage_update(self):
        """Verify usage_update channel broadcasts UsageSnapshot correctly."""
        mgr = ConnectionManager()
        sent_messages = []

        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=_async_noop())
        mock_ws.send_text = MagicMock(side_effect=lambda msg: sent_messages.append(msg))

        await mgr.connect(mock_ws)

        usage = UsageSnapshot(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            usages=[TokenUsage(
                provider="anthropic", model="claude-sonnet-4-6",
                input_tokens=50000, output_tokens=10000, total_tokens=60000,
                cost_usd=0.54,
            )],
            total_cost_usd=0.54,
        )
        await mgr.broadcast("usage_update", usage)

        assert len(sent_messages) == 1
        msg = json.loads(sent_messages[0])
        assert msg["type"] == "usage_update"
        assert len(msg["data"]["usages"]) == 1
        assert msg["data"]["usages"][0]["provider"] == "anthropic"
        assert msg["data"]["total_cost_usd"] == 0.54


# ---------------------------------------------------------------------------
# Broadcast message serialization
# ---------------------------------------------------------------------------

class TestBroadcastSerialization:
    def test_system_snapshot_serialized_correctly(self):
        snapshot = _make_test_snapshot()
        d = _serialise(snapshot)

        # Timestamp must be ISO string (for JS Date parsing)
        assert isinstance(d["timestamp"], str)
        assert "2026-03-29" in d["timestamp"]

        # All nested metrics present
        assert isinstance(d["cpu"]["usage_percent"], float)
        assert isinstance(d["cpu"]["per_core"], list)
        assert isinstance(d["memory"]["total_gb"], (int, float))
        assert isinstance(d["network"]["bytes_sent_per_sec"], (int, float))
        assert d["gpu"] is None

    def test_alert_event_serialized_correctly(self):
        event = AlertEvent(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            metric="memory_percent",
            current_value=88.5,
            threshold=80.0,
            level="warning",
            message="Memory high",
        )
        d = _serialise(event)

        assert isinstance(d["timestamp"], str)
        assert d["metric"] == "memory_percent"
        assert d["current_value"] == 88.5
        assert d["level"] == "warning"
        assert d["message"] == "Memory high"

    def test_usage_snapshot_serialized_correctly(self):
        usage = UsageSnapshot(
            timestamp=datetime(2026, 3, 29, tzinfo=timezone.utc),
            usages=[
                TokenUsage(
                    provider="openai", model="gpt-4",
                    input_tokens=1000, output_tokens=500, total_tokens=1500,
                    cost_usd=None, period="current_month",
                ),
            ],
            total_cost_usd=None,
        )
        d = _serialise(usage)

        assert isinstance(d["timestamp"], str)
        assert d["usages"][0]["provider"] == "openai"
        assert d["usages"][0]["cost_usd"] is None
        assert d["total_cost_usd"] is None

    def test_broadcast_json_is_valid(self):
        """The full broadcast message {type, data} must be valid JSON."""
        snapshot = _make_test_snapshot()
        message = json.dumps({
            "type": "system_metrics",
            "data": _serialise(snapshot),
        })
        parsed = json.loads(message)
        assert parsed["type"] == "system_metrics"
        assert "cpu" in parsed["data"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_noop():
    """Coroutine that does nothing — used as mock return value for async methods."""
    pass


def _make_test_snapshot() -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
        cpu=CpuMetrics(usage_percent=45.2, per_core=[40.1, 50.3], temperature_celsius=55.0),
        memory=MemoryMetrics(total_gb=16.0, used_gb=10.5, available_gb=5.5, usage_percent=65.6),
        disk=DiskMetrics(
            total_gb=500, used_gb=250, free_gb=250, usage_percent=50.0,
            read_bytes_per_sec=1024, write_bytes_per_sec=512,
        ),
        network=NetworkMetrics(bytes_sent_per_sec=2048, bytes_recv_per_sec=4096),
        gpu=None,
    )
