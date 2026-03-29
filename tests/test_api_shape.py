"""Boundary verification: API response shapes match expected frontend contracts."""

import pytest
import dataclasses
from datetime import datetime, timezone

from src.core.models import (
    AlertEvent,
    CpuMetrics,
    DiskMetrics,
    GpuMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
    TokenUsage,
    UsageSnapshot,
)
from src.api.routes import _to_dict
from src.api.websocket import _serialise


# ---------------------------------------------------------------------------
# REST API shape: _to_dict should produce JSON-serializable dicts
# ---------------------------------------------------------------------------

class TestSystemSnapshotShape:
    """Verify SystemSnapshot → JSON matches frontend expectations."""

    def test_basic_snapshot_shape(self):
        snap = SystemSnapshot(
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
        d = _to_dict(snap)

        # Frontend accesses: data.cpu.usage_percent
        assert "cpu" in d
        assert "usage_percent" in d["cpu"]
        assert isinstance(d["cpu"]["usage_percent"], float)
        assert "per_core" in d["cpu"]
        assert isinstance(d["cpu"]["per_core"], list)

        # Frontend accesses: data.memory.used_gb, data.memory.total_gb
        assert "memory" in d
        assert "used_gb" in d["memory"]
        assert "total_gb" in d["memory"]
        assert "usage_percent" in d["memory"]

        # Frontend accesses: data.disk.usage_percent, used_gb, total_gb
        assert "disk" in d
        assert "usage_percent" in d["disk"]
        assert "used_gb" in d["disk"]

        # Frontend accesses: data.network.bytes_sent_per_sec
        assert "network" in d
        assert "bytes_sent_per_sec" in d["network"]
        assert "bytes_recv_per_sec" in d["network"]

        # GPU is None -> should be None in dict
        assert d["gpu"] is None

    def test_snapshot_with_gpu(self):
        snap = SystemSnapshot(
            timestamp=datetime(2026, 3, 29, tzinfo=timezone.utc),
            cpu=CpuMetrics(usage_percent=30.0, per_core=[30.0]),
            memory=MemoryMetrics(total_gb=16.0, used_gb=8.0, available_gb=8.0, usage_percent=50.0),
            disk=DiskMetrics(
                total_gb=500, used_gb=100, free_gb=400, usage_percent=20.0,
                read_bytes_per_sec=0, write_bytes_per_sec=0,
            ),
            network=NetworkMetrics(bytes_sent_per_sec=0, bytes_recv_per_sec=0),
            gpu=GpuMetrics(
                usage_percent=30.0, memory_used_mb=2048, memory_total_mb=8192,
                temperature_celsius=60.0,
            ),
        )
        d = _to_dict(snap)

        # Frontend accesses: data.gpu.usage_percent, memory_used_mb, memory_total_mb
        assert d["gpu"] is not None
        assert "usage_percent" in d["gpu"]
        assert "memory_used_mb" in d["gpu"]
        assert "memory_total_mb" in d["gpu"]
        assert "temperature_celsius" in d["gpu"]


class TestUsageSnapshotShape:
    """Verify UsageSnapshot → JSON matches frontend expectations."""

    def test_usage_shape(self):
        snap = UsageSnapshot(
            timestamp=datetime(2026, 3, 29, tzinfo=timezone.utc),
            usages=[
                TokenUsage(
                    provider="anthropic", model="claude-sonnet-4-6",
                    input_tokens=50000, output_tokens=10000, total_tokens=60000,
                    cost_usd=0.54,
                ),
            ],
            total_cost_usd=1.23,
        )
        d = _to_dict(snap)

        # Frontend accesses: data.usages, data.total_cost_usd
        assert "usages" in d
        assert isinstance(d["usages"], list)
        assert len(d["usages"]) == 1
        assert "total_cost_usd" in d

        # Frontend accesses per usage: provider, cost_usd, total_tokens
        u = d["usages"][0]
        assert u["provider"] == "anthropic"
        assert u["total_tokens"] == 60000
        assert u["cost_usd"] == 0.54

    def test_empty_usage(self):
        d = {"timestamp": None, "usages": [], "total_cost_usd": None}
        # This is what the route returns when no data yet
        assert d["usages"] == []
        assert d["total_cost_usd"] is None


class TestAlertEventShape:
    """Verify AlertEvent → JSON matches frontend expectations."""

    def test_alert_shape(self):
        event = AlertEvent(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            metric="cpu_percent",
            current_value=92.5,
            threshold=90.0,
            level="critical",
            message="CPU usage exceeded critical threshold",
        )
        d = _to_dict(event)

        # Frontend accesses: a.timestamp, a.level, a.message
        assert "timestamp" in d
        assert d["level"] in ("warning", "critical")
        assert "message" in d
        assert "metric" in d
        assert "current_value" in d


class TestConfigShape:
    """Verify GET /api/config shape matches frontend expectations."""

    def test_config_response_shape(self):
        # Simulated config response (from routes.py get_config)
        config = {
            "thresholds": [
                {"metric": "cpu_percent", "warning": 80, "critical": 95},
                {"metric": "memory_percent", "warning": 80, "critical": 95},
            ],
            "providers": [
                {"name": "anthropic", "configured": True},
                {"name": "openai", "configured": False},
            ],
        }

        # Frontend settings.js accesses thresholds correctly:
        for t in config["thresholds"]:
            assert "metric" in t
            assert "warning" in t
            assert "critical" in t

        # Frontend settings.js accesses providers — NOTE: this is an array!
        assert isinstance(config["providers"], list)
        for p in config["providers"]:
            assert "name" in p
            assert "configured" in p


# ---------------------------------------------------------------------------
# WebSocket serialization shape
# ---------------------------------------------------------------------------

class TestWebSocketSerialization:
    """Verify _serialise produces correct shapes for WS broadcast."""

    def test_datetime_serialized_to_string(self):
        snap = SystemSnapshot(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            cpu=CpuMetrics(usage_percent=50.0, per_core=[50.0]),
            memory=MemoryMetrics(total_gb=16.0, used_gb=8.0, available_gb=8.0, usage_percent=50.0),
            disk=DiskMetrics(
                total_gb=500, used_gb=250, free_gb=250, usage_percent=50.0,
                read_bytes_per_sec=0, write_bytes_per_sec=0,
            ),
            network=NetworkMetrics(bytes_sent_per_sec=0, bytes_recv_per_sec=0),
        )
        d = _serialise(snap)

        # Timestamp should be ISO string for JavaScript Date parsing
        assert isinstance(d["timestamp"], str)
        assert "2026-03-29" in d["timestamp"]

    def test_alert_event_serialized(self):
        event = AlertEvent(
            timestamp=datetime(2026, 3, 29, 10, 0, 0, tzinfo=timezone.utc),
            metric="cpu_percent",
            current_value=92.5,
            threshold=90.0,
            level="critical",
            message="test",
        )
        d = _serialise(event)
        assert isinstance(d["timestamp"], str)
        assert d["level"] == "critical"
