"""ZhipuAIUsageAdapter — fetch GLM quota usage from ZhipuAI monitor API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

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

        if data.get("code") != 200 or not data.get("data"):
            logger.warning("ZhipuAI unexpected response: %s", data.get("msg"))
            return []

        payload = data["data"]
        limits = payload.get("limits", [])
        level = payload.get("level", "unknown")

        results: list[TokenUsage] = []
        for limit in limits:
            limit_type = limit.get("type", "")
            percentage = limit.get("percentage", 0)
            usage = limit.get("usage")
            current = limit.get("currentValue")
            remaining = limit.get("remaining")

            reset_ts = limit.get("nextResetTime")
            reset_text = None
            if reset_ts:
                reset_dt = datetime.fromtimestamp(reset_ts / 1000, tz=timezone.utc)
                reset_text = reset_dt.strftime("%Y-%m-%d %H:%M UTC")

            if limit_type == "TIME_LIMIT":
                results.append(TokenUsage(
                    provider="zhipuai",
                    model=f"time-limit ({level})",
                    input_tokens=current or 0,
                    output_tokens=0,
                    total_tokens=current or 0,
                    cost_usd=None,
                    period="5h_rolling",
                    quota_limit=usage,
                    quota_percentage=percentage,
                    reset_text=reset_text,
                ))
            elif limit_type == "TOKENS_LIMIT":
                results.append(TokenUsage(
                    provider="zhipuai",
                    model=f"tokens-limit ({level})",
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    cost_usd=None,
                    period="monthly",
                    quota_percentage=percentage,
                    reset_text=reset_text,
                ))

        return results
