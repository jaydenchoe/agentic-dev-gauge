"""Fetch LM Studio local LLM status and benchmark tok/s."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import psutil

logger = logging.getLogger(__name__)


@dataclass
class LMStudioUsage:
    model: Optional[str] = None
    parameter_size: Optional[str] = None
    vram_gb: Optional[float] = None
    vram_percent: Optional[float] = None
    base_url: Optional[str] = None
    tok_per_sec: Optional[float] = None
    context_length: Optional[int] = None
    ttft_ms: Optional[float] = None
    prefill_tok_per_sec: Optional[float] = None
    benchmark_ago: Optional[str] = None
    available: bool = False

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "parameter_size": self.parameter_size,
            "vram_gb": self.vram_gb,
            "vram_percent": self.vram_percent,
            "base_url": self.base_url,
            "tok_per_sec": self.tok_per_sec,
            "context_length": self.context_length,
            "ttft_ms": self.ttft_ms,
            "prefill_tok_per_sec": self.prefill_tok_per_sec,
            "benchmark_ago": self.benchmark_ago,
            "available": self.available,
        }


async def fetch_lm_studio_status(
    host: str = "127.0.0.1",
    port: int = 1234,
) -> Optional[LMStudioUsage]:
    """Get currently loaded model info from LM Studio."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{host}:{port}/api/v0/models")
            if resp.status_code != 200:
                return LMStudioUsage(available=False)
            data = resp.json()
    except Exception:
        return LMStudioUsage(available=False)

    models = data.get("data", [])
    loaded_models = [m for m in models if m.get("state") == "loaded"]
    if not loaded_models:
        return LMStudioUsage(available=True)

    m = loaded_models[0]
    context_length = m.get("loaded_context_length")
    if context_length is None:
        context_length = m.get("max_context_length")

    return LMStudioUsage(
        model=m.get("id"),
        parameter_size=None,
        vram_gb=None,
        vram_percent=None,
        context_length=context_length,
        available=True,
    )


async def benchmark_lm_studio(
    host: str = "127.0.0.1",
    port: int = 1234,
) -> Optional[dict]:
    """Run a short benchmark and return metrics. Returns None if unavailable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{host}:{port}/api/v0/models")
            if resp.status_code != 200:
                return None
            models = resp.json().get("data", [])
            loaded_models = [m for m in models if m.get("state") == "loaded"]
            if not loaded_models:
                return None
            model_id = loaded_models[0]["id"]

        async with httpx.AsyncClient(timeout=60.0) as client:
            start = time.monotonic()
            resp = await client.post(
                f"http://{host}:{port}/api/v0/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 20,
                    "stream": False,
                },
            )
            elapsed = time.monotonic() - start
            if resp.status_code != 200:
                return None
            data = resp.json()

        usage = data.get("usage", {})
        stats = data.get("stats")
        ttft_ms = None
        prefill_tok_per_sec = None

        if stats is not None:
            tok_per_sec = round(stats["tokens_per_second"], 1)
            time_to_first_token = stats.get("time_to_first_token")
            if time_to_first_token is not None:
                ttft_ms = round(time_to_first_token * 1000, 0)
            prompt_tokens = usage.get("prompt_tokens", 0)
            if prompt_tokens > 0 and time_to_first_token and time_to_first_token > 0:
                prefill_tok_per_sec = round(prompt_tokens / time_to_first_token, 1)
        else:
            eval_count = usage.get("completion_tokens", 0)
            if eval_count <= 0 or elapsed <= 0:
                return None
            tok_per_sec = round(eval_count / elapsed, 1)

        return {
            "tok_per_sec": tok_per_sec,
            "ttft_ms": ttft_ms,
            "prefill_tok_per_sec": prefill_tok_per_sec,
        }
    except Exception as exc:
        logger.warning("LM Studio benchmark failed: %s", exc)
    return None
