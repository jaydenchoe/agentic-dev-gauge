"""PsutilMetricsAdapter — cross-platform system metrics via psutil."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import psutil

from src.core.models import (
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    NetworkMetrics,
    SystemSnapshot,
)
from src.core.ports.metrics import MetricsPort

logger = logging.getLogger(__name__)


class PsutilMetricsAdapter(MetricsPort):
    """Collect CPU, memory, disk, and network metrics using psutil."""

    def __init__(self) -> None:
        # Prime cpu_percent so the first real call returns a meaningful value.
        psutil.cpu_percent(interval=None, percpu=True)
        self._prev_net = psutil.net_io_counters()
        self._prev_disk_io = psutil.disk_io_counters()
        self._prev_ts = datetime.now(timezone.utc)

    async def is_available(self) -> bool:
        return True

    async def collect(self) -> SystemSnapshot:
        return await asyncio.to_thread(self._collect_sync)

    # ------------------------------------------------------------------
    def _collect_sync(self) -> SystemSnapshot:
        now = datetime.now(timezone.utc)
        elapsed = max((now - self._prev_ts).total_seconds(), 0.1)

        cpu = self._cpu()
        memory = self._memory()
        disk = self._disk(elapsed)
        network = self._network(elapsed)

        self._prev_ts = now

        return SystemSnapshot(
            timestamp=now,
            cpu=cpu,
            memory=memory,
            disk=disk,
            network=network,
            gpu=None,
        )

    # --- helpers -------------------------------------------------------
    @staticmethod
    def _cpu() -> CpuMetrics:
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        freq = psutil.cpu_freq()
        return CpuMetrics(
            usage_percent=sum(per_core) / len(per_core) if per_core else 0.0,
            per_core=per_core,
            frequency_mhz=freq.current if freq else None,
            temperature_celsius=None,
        )

    @staticmethod
    def _memory() -> MemoryMetrics:
        vm = psutil.virtual_memory()
        total_gb = vm.total / (1024**3)
        used_gb = vm.used / (1024**3)
        available_gb = vm.available / (1024**3)
        return MemoryMetrics(
            total_gb=total_gb,
            used_gb=used_gb,
            available_gb=available_gb,
            usage_percent=round(used_gb / total_gb * 100, 1) if total_gb else 0.0,
        )

    @staticmethod
    def _disk_path() -> str:
        """Return the most representative disk path for the current OS."""
        import sys
        if sys.platform == "darwin":
            import os
            data_vol = "/System/Volumes/Data"
            if os.path.isdir(data_vol):
                return data_vol
        return "/"

    def _disk(self, elapsed: float) -> DiskMetrics:
        usage = psutil.disk_usage(self._disk_path())
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        try:
            dio = psutil.disk_io_counters()
            read_bps = (dio.read_bytes - self._prev_disk_io.read_bytes) / elapsed
            write_bps = (dio.write_bytes - self._prev_disk_io.write_bytes) / elapsed
            self._prev_disk_io = dio
        except Exception:
            read_bps = 0.0
            write_bps = 0.0
        return DiskMetrics(
            total_gb=total_gb,
            used_gb=used_gb,
            free_gb=free_gb,
            usage_percent=round(used_gb / total_gb * 100, 1) if total_gb else 0.0,
            read_bytes_per_sec=max(read_bps, 0.0),
            write_bytes_per_sec=max(write_bps, 0.0),
        )

    def _network(self, elapsed: float) -> NetworkMetrics:
        try:
            nio = psutil.net_io_counters()
            sent_bps = (nio.bytes_sent - self._prev_net.bytes_sent) / elapsed
            recv_bps = (nio.bytes_recv - self._prev_net.bytes_recv) / elapsed
            self._prev_net = nio
        except Exception:
            sent_bps = 0.0
            recv_bps = 0.0
        return NetworkMetrics(
            bytes_sent_per_sec=max(sent_bps, 0.0),
            bytes_recv_per_sec=max(recv_bps, 0.0),
        )
