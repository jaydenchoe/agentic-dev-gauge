"""OpenAIUsageAdapter — fetch token usage from OpenAI organization API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)


class OpenAIUsageAdapter(UsagePort):
    BASE_URL = "https://api.openai.com/v1/organization/usage"

    def provider_name(self) -> str:
        return "openai"

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        now = datetime.now(timezone.utc)
        start_ts = int((now - timedelta(days=30)).timestamp())

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"start_time": start_ts},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("OpenAI usage API error: %s", exc)
            return []

        return self._parse(data)

    @staticmethod
    def _parse(data: dict) -> list[TokenUsage]:
        model_agg: dict[str, dict] = {}
        for bucket in data.get("data", []):
            result = bucket.get("result", {})
            model = result.get("model", "unknown")
            agg = model_agg.setdefault(model, {"input": 0, "output": 0})
            agg["input"] += result.get("input_tokens", 0)
            agg["output"] += result.get("output_tokens", 0)

        results: list[TokenUsage] = []
        for model, tokens in model_agg.items():
            inp, out = tokens["input"], tokens["output"]
            results.append(
                TokenUsage(
                    provider="openai",
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    total_tokens=inp + out,
                    cost_usd=None,
                    period="current_month",
                )
            )
        return results
