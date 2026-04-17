"""DisplayService — render dashboard pages and push to an external display on a timer."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from src.adapters.display.renderer import (
    png_bytes,
    render_claude,
    render_local_llm,
    render_other,
    render_system,
)
from src.core.ports.display import DisplayPort

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.services.monitor_service import MonitorService
    from src.services.usage_service import UsageService

logger = logging.getLogger(__name__)

_PAGE_COUNT = 4


class DisplayService:
    """Rotate through 4 carousel pages (SYSTEM / CLAUDE / OTHER / LOCAL LLM)."""

    def __init__(
        self,
        adapter: DisplayPort,
        monitor_svc: "MonitorService",
        usage_svc: "UsageService",
        interval_sec: float = 5.0,
    ) -> None:
        self._adapter = adapter
        self._monitor = monitor_svc
        self._usage = usage_svc
        self._interval = interval_sec
        self._page_index = 0
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("Display tick failed")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        page = self._page_index % _PAGE_COUNT
        self._page_index += 1
        img = self._render_page(page)
        ok = await self._adapter.push_png(png_bytes(img))
        if not ok:
            logger.debug("Display push returned False (page %s)", page)

    def _render_page(self, page: int):
        if page == 0:
            return self._render_system()
        if page == 1:
            return self._render_claude()
        if page == 2:
            return self._render_other()
        return self._render_local_llm()

    def _render_system(self):
        snap = self._monitor.latest
        if snap is None:
            return render_system(None, None, None)
        return render_system(
            cpu=snap.cpu.usage_percent,
            mem=snap.memory.usage_percent,
            disk=snap.disk.usage_percent,
        )

    def _render_claude(self):
        c = self._usage.claude_web_latest
        if c is None:
            return render_claude(None, None, None)
        return render_claude(
            session=c.session_used_percent,
            weekly=c.weekly_all_used_percent,
            sonnet=c.weekly_sonnet_used_percent,
        )

    def _render_other(self):
        codex_pct = self._pct_from_usages("codex")
        zhipu_pct = self._pct_from_usages("zhipuai")
        copilot_pct = self._copilot_pct()
        return render_other(codex=codex_pct, copilot=copilot_pct, zhipu=zhipu_pct)

    def _render_local_llm(self):
        o = self._usage.ollama_latest
        if o is None or not o.available:
            return render_local_llm(None, None, None)
        return render_local_llm(
            model=o.model,
            vram_pct=o.vram_percent,
            tok_per_sec=o.tok_per_sec,
        )

    def _pct_from_usages(self, provider: str) -> Optional[float]:
        snapshot = self._usage.latest
        if snapshot is None:
            return None
        for u in snapshot.usages:
            if u.provider == provider and u.quota_percentage is not None:
                return u.quota_percentage
        return None

    def _copilot_pct(self) -> Optional[float]:
        c = self._usage.copilot_api_latest
        if c is None:
            return None
        for q in c.quotas:
            if q.quota_id == "premium_interactions" and not q.unlimited:
                return q.percent_used
        return None
