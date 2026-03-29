"""Mock system metrics adapter for development/fallback."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from src.core.models import (
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
)
from src.core.ports.metrics import MetricsPort


class MockMetricsAdapter(MetricsPort):
    async def collect(self) -> SystemSnapshot:
        return SystemSnapshot(
            timestamp=datetime.now(timezone.utc),
            cpu=CpuMetrics(
                usage_percent=random.uniform(10, 60),
                per_core=[random.uniform(5, 80) for _ in range(4)],
                frequency_mhz=3200.0,
            ),
            memory=MemoryMetrics(
                total_gb=16.0,
                used_gb=round(random.uniform(6, 14), 1),
                available_gb=round(random.uniform(2, 10), 1),
                usage_percent=random.uniform(40, 85),
            ),
            disk=DiskMetrics(
                total_gb=500.0,
                used_gb=250.0,
                free_gb=250.0,
                usage_percent=50.0,
                read_bytes_per_sec=random.uniform(0, 50_000_000),
                write_bytes_per_sec=random.uniform(0, 30_000_000),
            ),
            network=NetworkMetrics(
                bytes_sent_per_sec=random.uniform(0, 1_000_000),
                bytes_recv_per_sec=random.uniform(0, 5_000_000),
            ),
        )

    async def is_available(self) -> bool:
        return True
