"""Fetch Ollama local LLM status and benchmark tok/s."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import psutil

logger = logging.getLogger(__name__)

_CACHE_TTL = 60  # 1 minute for status
_cache: dict[str, tuple[float, "OllamaUsage"]] = {}


@dataclass
class OllamaUsage:
    model: Optional[str] = None  # e.g. "qwen3.5:35b-a3b"
    parameter_size: Optional[str] = None  # e.g. "36.0B"
    vram_gb: Optional[float] = None  # VRAM usage in GB
    vram_percent: Optional[float] = None  # VRAM as % of total unified memory
    base_url: Optional[str] = None
    tok_per_sec: Optional[float] = None  # benchmark result
    benchmark_ago: Optional[str] = None  # "2m ago"
    available: bool = False

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "parameter_size": self.parameter_size,
            "vram_gb": self.vram_gb,
            "vram_percent": self.vram_percent,
            "base_url": self.base_url,
            "tok_per_sec": self.tok_per_sec,
            "benchmark_ago": self.benchmark_ago,
            "available": self.available,
        }


async def fetch_ollama_status(
    host: str = "127.0.0.1",
    port: int = 11434,
) -> Optional[OllamaUsage]:
    """Get currently loaded model info from Ollama."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{host}:{port}/api/ps")
            if resp.status_code != 200:
                return OllamaUsage(available=False)
            data = resp.json()
    except Exception:
        return OllamaUsage(available=False)

    models = data.get("models", [])
    if not models:
        return OllamaUsage(available=True)  # Ollama running but no model loaded

    m = models[0]  # First loaded model
    vram_bytes = m.get("size_vram", 0)
    details = m.get("details", {})
    total_mem = psutil.virtual_memory().total
    vram_pct = round(vram_bytes / total_mem * 100, 1) if vram_bytes and total_mem else None

    return OllamaUsage(
        model=m.get("name"),
        parameter_size=details.get("parameter_size"),
        vram_gb=round(vram_bytes / (1024**3), 1) if vram_bytes else None,
        vram_percent=vram_pct,
        available=True,
    )


async def benchmark_ollama(
    host: str = "127.0.0.1",
    port: int = 11434,
) -> Optional[float]:
    """Run a short benchmark and return tok/s. Returns None if unavailable."""
    try:
        # Check if a model is loaded first
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{host}:{port}/api/ps")
            if resp.status_code != 200:
                return None
            models = resp.json().get("models", [])
            if not models:
                return None
            model_name = models[0]["name"]

        # Run short inference
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"http://{host}:{port}/api/generate",
                json={
                    "model": model_name,
                    "prompt": "/no_think Hello",
                    "stream": False,
                    "options": {"num_predict": 20},
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()

        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 0)
        if eval_count > 0 and eval_duration > 0:
            return round(eval_count / (eval_duration / 1e9), 1)
    except Exception as exc:
        logger.warning("Ollama benchmark failed: %s", exc)
    return None
