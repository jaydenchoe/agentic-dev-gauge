"""ZhipuAIUsageAdapter — fetch GLM token usage from ZhipuAI API."""

from __future__ import annotations

import logging

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)


class ZhipuAIUsageAdapter(UsagePort):
    BASE_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"

    def provider_name(self) -> str:
        return "zhipuai"

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ZhipuAI usage API error: %s", exc)
            return []

        used = data.get("used", 0)
        return [
            TokenUsage(
                provider="zhipuai",
                model="glm",
                input_tokens=used,
                output_tokens=0,
                total_tokens=used,
                cost_usd=None,
                period="current_month",
            )
        ]
