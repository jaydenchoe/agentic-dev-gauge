"""AnthropicUsageAdapter — fetch Claude token usage from Anthropic API."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)

# Rough per-token cost estimates (USD per 1M tokens).
_COST_PER_M: dict[str, dict[str, float]] = {
    "opus": {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 0.25, "output": 1.25},
}

_MAX_PAGES = 50  # safety limit
_CACHE_TTL = 300  # 5 minutes
_usage_cache: dict[str, tuple[float, list["TokenUsage"]]] = {}


class AnthropicUsageAdapter(UsagePort):
    BASE_URL = "https://api.anthropic.com/v1/organizations"

    def provider_name(self) -> str:
        return "anthropic"

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        cache_key = api_key[:10]
        cached = _usage_cache.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL:
            return cached[1]

        from src.adapters.ai_usage.anthropic_throttle import throttle
        await throttle()

        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        model_agg: dict[str, dict[str, int]] = {}
        next_page: str | None = None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for _ in range(_MAX_PAGES):
                    params: list[tuple[str, str]] = [
                        ("starting_at", start.strftime("%Y-%m-%dT%H:%M:%SZ")),
                        ("ending_at", now.strftime("%Y-%m-%dT%H:%M:%SZ")),
                        ("group_by[]", "model"),
                    ]
                    if next_page:
                        params.append(("page", next_page))

                    resp = await client.get(
                        f"{self.BASE_URL}/usage_report/messages",
                        headers=headers,
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    # Aggregate results across daily buckets
                    for bucket in data.get("data", []):
                        for result in bucket.get("results", []):
                            model = result.get("model", "unknown")
                            agg = model_agg.setdefault(model, {"input": 0, "output": 0})
                            agg["input"] += result.get("input_tokens", 0)
                            agg["output"] += result.get("output_tokens", 0)

                    if not data.get("has_more"):
                        break
                    next_page = data.get("next_page")
                    if not next_page:
                        break

        except httpx.HTTPStatusError as exc:
            logger.warning("Anthropic usage API %s — body: %s", exc.response.status_code, exc.response.text[:500])
            return []
        except httpx.HTTPError as exc:
            logger.warning("Anthropic usage API error: %s", exc)
            return []

        results: list[TokenUsage] = []
        for model, tokens in model_agg.items():
            inp, out = tokens["input"], tokens["output"]
            cost = _estimate_cost(model, inp, out)
            results.append(
                TokenUsage(
                    provider="anthropic",
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    total_tokens=inp + out,
                    cost_usd=cost,
                    period="current_month",
                )
            )
        _usage_cache[cache_key] = (time.time(), results)
        return results


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    for tier, rates in _COST_PER_M.items():
        if tier in model.lower():
            return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    # Default to sonnet pricing.
    r = _COST_PER_M["sonnet"]
    return (input_tokens * r["input"] + output_tokens * r["output"]) / 1_000_000
