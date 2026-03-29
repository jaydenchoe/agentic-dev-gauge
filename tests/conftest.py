"""Shared fixtures for Tiny Monitor tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

# Ensure project root on sys.path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.core.models import (
    AlertEvent,
    CpuMetrics,
    DiskMetrics,
    GpuMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
    ThresholdConfig,
    TokenUsage,
    UsageSnapshot,
)
from src.core.ports.metrics import MetricsPort
from src.core.ports.notification import NotificationPort
from src.core.ports.usage import UsagePort


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------

class MockMetricsAdapter(MetricsPort):
    """Returns a fixed SystemSnapshot for testing."""

    def __init__(self, snapshot: SystemSnapshot | None = None) -> None:
        self._snapshot = snapshot or _default_snapshot()

    async def is_available(self) -> bool:
        return True

    async def collect(self) -> SystemSnapshot:
        return self._snapshot


class MockUsageAdapter(UsagePort):
    """Returns fixed TokenUsage data."""

    def __init__(self, provider: str = "anthropic", usages: list[TokenUsage] | None = None) -> None:
        self._provider = provider
        self._usages = usages or [
            TokenUsage(
                provider=provider,
                model="test-model",
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
                cost_usd=0.05,
            )
        ]

    def provider_name(self) -> str:
        return self._provider

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        return self._usages


class MockNotifier(NotificationPort):
    """Records alert calls for assertions."""

    def __init__(self) -> None:
        self.sent_alerts: list[AlertEvent] = []

    async def send_alert(self, event: AlertEvent) -> bool:
        self.sent_alerts.append(event)
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_snapshot() -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=datetime.now(timezone.utc),
        cpu=CpuMetrics(usage_percent=45.0, per_core=[40.0, 50.0], frequency_mhz=2400.0),
        memory=MemoryMetrics(total_gb=16.0, used_gb=10.0, available_gb=6.0, usage_percent=62.5),
        disk=DiskMetrics(
            total_gb=500.0, used_gb=250.0, free_gb=250.0, usage_percent=50.0,
            read_bytes_per_sec=1024.0, write_bytes_per_sec=512.0,
        ),
        network=NetworkMetrics(bytes_sent_per_sec=2048.0, bytes_recv_per_sec=4096.0),
        gpu=None,
    )


def make_snapshot(**overrides) -> SystemSnapshot:
    """Create a SystemSnapshot with optional CPU/memory/disk percent overrides."""
    snap = _default_snapshot()
    if "cpu_percent" in overrides:
        snap.cpu.usage_percent = overrides["cpu_percent"]
    if "memory_percent" in overrides:
        snap.memory.usage_percent = overrides["memory_percent"]
    if "disk_percent" in overrides:
        snap.disk.usage_percent = overrides["disk_percent"]
    if "gpu" in overrides:
        snap.gpu = overrides["gpu"]
    return snap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_metrics():
    return MockMetricsAdapter()


@pytest.fixture
def mock_usage():
    return MockUsageAdapter()


@pytest.fixture
def mock_notifier():
    return MockNotifier()


@pytest.fixture
def default_thresholds():
    return [
        ThresholdConfig(metric="cpu_percent", warning=80, critical=95),
        ThresholdConfig(metric="memory_percent", warning=80, critical=95),
        ThresholdConfig(metric="disk_percent", warning=85, critical=95),
        ThresholdConfig(metric="token_cost", warning=10.0, critical=50.0),
    ]
