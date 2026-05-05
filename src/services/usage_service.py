"""Collects AI token usage from multiple UsagePort adapters."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlparse

from src.adapters.ai_usage.claude_web_usage import ClaudeWebUsage, fetch_claude_web_usage
from src.adapters.ai_usage.copilot_api_usage import CopilotApiUsage, fetch_copilot_api_usage
from src.adapters.ai_usage.lm_studio_usage import LMStudioUsage, fetch_lm_studio_status, benchmark_lm_studio
from src.adapters.ai_usage.ollama_usage import OllamaUsage, fetch_ollama_status, benchmark_ollama
from src.core.models import TokenUsage, UsageSnapshot
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)
_DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_DEFAULT_LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"


def _time_ago(ts: float) -> str:
    diff = int(time.time() - ts)
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    return f"{diff // 3600}h ago"


def _parse_ollama_endpoint(ollama_base_url: str) -> tuple[str, int]:
    candidate = (ollama_base_url or _DEFAULT_OLLAMA_BASE_URL).strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlparse(candidate)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    return host, port


def _parse_lm_studio_endpoint(lm_studio_base_url: str) -> tuple[str, int]:
    candidate = (lm_studio_base_url or _DEFAULT_LM_STUDIO_BASE_URL).strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlparse(candidate)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1234
    return host, port


class UsageService:
    def __init__(
        self,
        adapters: list[UsagePort],
        api_keys: dict[str, str],
        interval: float = 60.0,
        claude_web_cdp_port: int = 9222,
        claude_web_interval: float = 300.0,
        copilot_api_interval: float = 300.0,
        github_token: Optional[str] = None,
        ollama_status_interval: float = 60.0,
        ollama_benchmark_interval: float = 300.0,
        ollama_base_url: str = _DEFAULT_OLLAMA_BASE_URL,
        lm_studio_status_interval: float = 60.0,
        lm_studio_benchmark_interval: float = 300.0,
        lm_studio_base_url: str = _DEFAULT_LM_STUDIO_BASE_URL,
    ) -> None:
        self._adapters = adapters
        self._api_keys = api_keys
        self._interval = interval
        self._latest: Optional[UsageSnapshot] = None
        self._task: Optional[asyncio.Task] = None
        # Claude web usage
        self._cdp_port = claude_web_cdp_port
        self._claude_web_interval = claude_web_interval
        self._claude_web_latest: Optional[ClaudeWebUsage] = None
        self._claude_web_task: Optional[asyncio.Task] = None
        # Copilot API usage
        self._github_token = github_token
        self._copilot_api_interval = copilot_api_interval
        self._copilot_api_latest: Optional[CopilotApiUsage] = None
        self._copilot_api_task: Optional[asyncio.Task] = None
        # Ollama
        self._ollama_status_interval = ollama_status_interval
        self._ollama_benchmark_interval = ollama_benchmark_interval
        self._ollama_latest: Optional[OllamaUsage] = None
        self._ollama_status_task: Optional[asyncio.Task] = None
        self._ollama_benchmark_task: Optional[asyncio.Task] = None
        self._ollama_last_benchmark_ts: float = 0
        self._ollama_base_url = (ollama_base_url or _DEFAULT_OLLAMA_BASE_URL).strip() or _DEFAULT_OLLAMA_BASE_URL
        self._ollama_host, self._ollama_port = _parse_ollama_endpoint(self._ollama_base_url)
        # LM Studio
        self._lm_studio_status_interval = lm_studio_status_interval
        self._lm_studio_benchmark_interval = lm_studio_benchmark_interval
        self._lm_studio_latest: LMStudioUsage | None = None
        self._lm_studio_status_task: asyncio.Task | None = None
        self._lm_studio_benchmark_task: asyncio.Task | None = None
        self._lm_studio_last_benchmark_ts: float = 0.0
        self._lm_studio_base_url = (lm_studio_base_url or _DEFAULT_LM_STUDIO_BASE_URL).strip().rstrip("/") or _DEFAULT_LM_STUDIO_BASE_URL
        self._lm_studio_host, self._lm_studio_port = _parse_lm_studio_endpoint(self._lm_studio_base_url)
        self._on_data_update: Optional[Callable[[str], None]] = None

    @property
    def latest(self) -> Optional[UsageSnapshot]:
        return self._latest

    @property
    def claude_web_latest(self) -> Optional[ClaudeWebUsage]:
        return self._claude_web_latest

    @property
    def copilot_api_latest(self) -> Optional[CopilotApiUsage]:
        return self._copilot_api_latest

    @property
    def ollama_latest(self) -> Optional[OllamaUsage]:
        return self._ollama_latest

    @property
    def lm_studio_latest(self) -> Optional[LMStudioUsage]:
        return self._lm_studio_latest

    def update_api_keys(self, api_keys: dict[str, str]) -> None:
        self._api_keys = api_keys

    def register_update_callback(self, cb: Callable[[str], None]) -> None:
        self._on_data_update = cb

    def _notify(self, source: str) -> None:
        if self._on_data_update is not None:
            try:
                self._on_data_update(source)
            except Exception:
                pass

    def update_ollama_base_url(self, ollama_base_url: str) -> None:
        self._ollama_base_url = (ollama_base_url or _DEFAULT_OLLAMA_BASE_URL).strip() or _DEFAULT_OLLAMA_BASE_URL
        self._ollama_host, self._ollama_port = _parse_ollama_endpoint(self._ollama_base_url)
        if self._ollama_latest:
            self._ollama_latest.base_url = self._ollama_base_url

    def update_lm_studio_base_url(self, lm_studio_base_url: str) -> None:
        self._lm_studio_base_url = (lm_studio_base_url or _DEFAULT_LM_STUDIO_BASE_URL).strip().rstrip("/") or _DEFAULT_LM_STUDIO_BASE_URL
        self._lm_studio_host, self._lm_studio_port = _parse_lm_studio_endpoint(self._lm_studio_base_url)
        if self._lm_studio_latest:
            self._lm_studio_latest.base_url = self._lm_studio_base_url

        status_was_started = self._lm_studio_status_task is not None
        benchmark_was_started = self._lm_studio_benchmark_task is not None
        for task in (self._lm_studio_status_task, self._lm_studio_benchmark_task):
            if task and not task.done():
                task.cancel()
        if status_was_started:
            self._lm_studio_status_task = asyncio.create_task(self._lm_studio_status_loop())
        if benchmark_was_started:
            self._lm_studio_benchmark_task = asyncio.create_task(self._lm_studio_benchmark_loop())

    async def collect_once(self) -> UsageSnapshot:
        all_usages: list[TokenUsage] = []
        for adapter in self._adapters:
            provider = adapter.provider_name()
            api_key = self._api_keys.get(provider)
            if not api_key:
                continue
            try:
                usages = await adapter.fetch_usage(api_key)
                all_usages.extend(usages)
            except Exception:
                logger.exception("Failed to fetch usage for %s", provider)

        total_cost = sum(u.cost_usd for u in all_usages if u.cost_usd is not None)
        snapshot = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=all_usages,
            total_cost_usd=total_cost if total_cost > 0 else None,
        )
        self._latest = snapshot
        self._notify("adapters")
        return snapshot

    async def _loop(self) -> None:
        while True:
            try:
                await self.collect_once()
            except Exception:
                logger.exception("Usage collection loop error")
            await asyncio.sleep(self._interval)

    async def _claude_web_loop(self) -> None:
        retry_interval = 15  # Fast retry until first success
        while True:
            try:
                result = await fetch_claude_web_usage(cdp_port=self._cdp_port)
                valid = result is not None and (
                    result.session_used_percent is not None
                    or result.weekly_all_used_percent is not None
                )
                if valid:
                    self._claude_web_latest = result
                    self._notify("claude")
                    retry_interval = self._claude_web_interval
                    logger.info("Claude web usage: session=%s%%, weekly=%s%%",
                                result.session_used_percent, result.weekly_all_used_percent)
                else:
                    logger.warning("Claude web usage returned no data, retrying in %ds", retry_interval)
            except Exception:
                logger.exception("Claude web usage collection error")
            await asyncio.sleep(retry_interval)

    async def _copilot_api_loop(self) -> None:
        while True:
            try:
                result = await fetch_copilot_api_usage(github_token=self._github_token)
                if result:
                    self._copilot_api_latest = result
                    self._notify("copilot")
                    premium = next((q for q in result.quotas if q.quota_id == "premium_interactions"), None)
                    if premium:
                        logger.info("Copilot API usage: premium=%s%% used (%s/%s)",
                                    premium.percent_used, premium.entitlement - premium.remaining, premium.entitlement)
            except Exception:
                logger.exception("Copilot API usage collection error")
            await asyncio.sleep(self._copilot_api_interval)

    async def _ollama_status_loop(self) -> None:
        while True:
            try:
                result = await fetch_ollama_status(self._ollama_host, self._ollama_port)
                if result:
                    result.base_url = self._ollama_base_url
                    # Preserve benchmark data from previous status
                    if self._ollama_latest and self._ollama_latest.tok_per_sec:
                        result.tok_per_sec = self._ollama_latest.tok_per_sec
                        result.ttft_ms = self._ollama_latest.ttft_ms
                        result.prefill_tok_per_sec = self._ollama_latest.prefill_tok_per_sec
                        result.benchmark_ago = _time_ago(self._ollama_last_benchmark_ts) if self._ollama_last_benchmark_ts else None
                    self._ollama_latest = result
                    self._notify("ollama")
                    if result.model:
                        logger.info("Ollama: %s (%.1f GB VRAM)", result.model, result.vram_gb or 0)
            except Exception:
                logger.exception("Ollama status collection error")
            await asyncio.sleep(self._ollama_status_interval)

    async def _ollama_benchmark_loop(self) -> None:
        while True:
            try:
                result = await benchmark_ollama(self._ollama_host, self._ollama_port)
                if result is not None:
                    self._ollama_last_benchmark_ts = time.time()
                    if self._ollama_latest:
                        self._ollama_latest.base_url = self._ollama_base_url
                        self._ollama_latest.tok_per_sec = result["tok_per_sec"]
                        self._ollama_latest.ttft_ms = result["ttft_ms"]
                        self._ollama_latest.prefill_tok_per_sec = result["prefill_tok_per_sec"]
                        self._ollama_latest.benchmark_ago = "just now"
                    logger.info("Ollama benchmark: %.1f tok/s", result["tok_per_sec"])
            except Exception:
                logger.exception("Ollama benchmark error")
            await asyncio.sleep(self._ollama_benchmark_interval)

    async def _lm_studio_status_loop(self) -> None:
        while True:
            try:
                result = await fetch_lm_studio_status(self._lm_studio_host, self._lm_studio_port)
                if result:
                    result.base_url = self._lm_studio_base_url
                    # Preserve benchmark data from previous status
                    if self._lm_studio_latest and self._lm_studio_latest.tok_per_sec:
                        result.tok_per_sec = self._lm_studio_latest.tok_per_sec
                        result.ttft_ms = self._lm_studio_latest.ttft_ms
                        result.prefill_tok_per_sec = self._lm_studio_latest.prefill_tok_per_sec
                        result.benchmark_ago = _time_ago(self._lm_studio_last_benchmark_ts) if self._lm_studio_last_benchmark_ts else None
                    self._lm_studio_latest = result
                    self._notify("lm_studio")
                    if result.model:
                        logger.info("LM Studio: %s (%.1f GB VRAM)", result.model, result.vram_gb or 0)
            except Exception:
                logger.exception("LM Studio status collection error")
            await asyncio.sleep(self._lm_studio_status_interval)

    async def _lm_studio_benchmark_loop(self) -> None:
        while True:
            try:
                result = await benchmark_lm_studio(self._lm_studio_host, self._lm_studio_port)
                if result is not None:
                    self._lm_studio_last_benchmark_ts = time.time()
                    if self._lm_studio_latest:
                        self._lm_studio_latest.base_url = self._lm_studio_base_url
                        self._lm_studio_latest.tok_per_sec = result["tok_per_sec"]
                        self._lm_studio_latest.ttft_ms = result["ttft_ms"]
                        self._lm_studio_latest.prefill_tok_per_sec = result["prefill_tok_per_sec"]
                        self._lm_studio_latest.benchmark_ago = "just now"
                    logger.info("LM Studio benchmark: %.1f tok/s", result["tok_per_sec"])
            except Exception:
                logger.exception("LM Studio benchmark error")
            await asyncio.sleep(self._lm_studio_benchmark_interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        if self._claude_web_task is None or self._claude_web_task.done():
            self._claude_web_task = asyncio.create_task(self._claude_web_loop())
        if self._copilot_api_task is None or self._copilot_api_task.done():
            self._copilot_api_task = asyncio.create_task(self._copilot_api_loop())
        if self._ollama_status_task is None or self._ollama_status_task.done():
            self._ollama_status_task = asyncio.create_task(self._ollama_status_loop())
        if self._ollama_benchmark_task is None or self._ollama_benchmark_task.done():
            self._ollama_benchmark_task = asyncio.create_task(self._ollama_benchmark_loop())
        if self._lm_studio_status_task is None or self._lm_studio_status_task.done():
            self._lm_studio_status_task = asyncio.create_task(self._lm_studio_status_loop())
        if self._lm_studio_benchmark_task is None or self._lm_studio_benchmark_task.done():
            self._lm_studio_benchmark_task = asyncio.create_task(self._lm_studio_benchmark_loop())

    async def stop(self) -> None:
        for task in (self._task, self._claude_web_task, self._copilot_api_task,
                     self._ollama_status_task, self._ollama_benchmark_task,
                     self._lm_studio_status_task, self._lm_studio_benchmark_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
