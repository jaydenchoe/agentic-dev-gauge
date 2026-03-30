"""Collects and caches system metrics via MetricsPort."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Optional

from src.core.models import SystemSnapshot
from src.core.ports.metrics import MetricsPort

logger = logging.getLogger(__name__)

MAX_HISTORY = 60  # keep last 60 snapshots


class MonitorService:
    def __init__(self, adapter: MetricsPort, interval: float = 2.0) -> None:
        self._adapter = adapter
        self._interval = interval
        self._history: deque[SystemSnapshot] = deque(maxlen=MAX_HISTORY)
        self._latest: Optional[SystemSnapshot] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def latest(self) -> Optional[SystemSnapshot]:
        return self._latest

    @property
    def history(self) -> list[SystemSnapshot]:
        return list(self._history)

    async def collect_once(self) -> SystemSnapshot:
        snapshot = await self._adapter.collect()
        self._latest = snapshot
        self._history.append(snapshot)
        return snapshot

    async def _loop(self) -> None:
        while True:
            try:
                await self.collect_once()
            except Exception:
                logger.exception("Failed to collect system metrics")
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
