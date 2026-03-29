"""MacmonMetricsAdapter — Apple Silicon GPU/temperature via macmon CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone

from src.core.models import (
    CpuMetrics,
    DiskMetrics,
    GpuMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
)
from src.core.ports.metrics import MetricsPort

logger = logging.getLogger(__name__)

# Timeout for macmon subprocess calls.
_MACMON_TIMEOUT = 5.0


class MacmonMetricsAdapter(MetricsPort):
    """Collect Apple-Silicon GPU and temperature metrics using macmon.

    This adapter is designed to *augment* a PsutilMetricsAdapter snapshot with
    GPU data and CPU temperature.  When used as the sole MetricsPort it will
    still return a full SystemSnapshot, but CPU/memory/disk/network fields will
    contain zeros — so prefer composing it with PsutilMetricsAdapter.
    """

    def __init__(self, psutil_adapter: MetricsPort | None = None) -> None:
        self._psutil = psutil_adapter

    async def is_available(self) -> bool:
        return shutil.which("macmon") is not None

    async def collect(self) -> SystemSnapshot:
        # Get base metrics from psutil if available.
        if self._psutil:
            snapshot = await self._psutil.collect()
        else:
            now = datetime.now(timezone.utc)
            snapshot = SystemSnapshot(
                timestamp=now,
                cpu=CpuMetrics(usage_percent=0, per_core=[]),
                memory=MemoryMetrics(total_gb=0, used_gb=0, available_gb=0, usage_percent=0),
                disk=DiskMetrics(
                    total_gb=0, used_gb=0, free_gb=0, usage_percent=0,
                    read_bytes_per_sec=0, write_bytes_per_sec=0,
                ),
                network=NetworkMetrics(bytes_sent_per_sec=0, bytes_recv_per_sec=0),
            )

        # Overlay macmon data.
        gpu, temperature = await self._read_macmon()
        snapshot.gpu = gpu
        if temperature is not None and snapshot.cpu.temperature_celsius is None:
            snapshot.cpu.temperature_celsius = temperature
        return snapshot

    # ------------------------------------------------------------------
    async def _read_macmon(self) -> tuple[GpuMetrics | None, float | None]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "macmon", "read", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_MACMON_TIMEOUT)
            data = json.loads(stdout)
            return self._parse(data)
        except FileNotFoundError:
            logger.debug("macmon not found — GPU metrics unavailable")
            return None, None
        except asyncio.TimeoutError:
            logger.warning("macmon timed out")
            return None, None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("macmon parse error: %s", exc)
            return None, None

    @staticmethod
    def _parse(data: dict) -> tuple[GpuMetrics | None, float | None]:
        gpu_usage = data.get("gpu_usage", {})
        gpu = GpuMetrics(
            usage_percent=gpu_usage.get("percent", 0.0),
            memory_used_mb=data.get("gpu_memory_used_mb", 0.0),
            memory_total_mb=data.get("gpu_memory_total_mb", 0.0),
            temperature_celsius=data.get("gpu_temp"),
        )
        temperature = data.get("cpu_temp_avg")
        return gpu, temperature
