"""CodexUsageAdapter — fetch ChatGPT Pro Codex quota usage from ChatGPT web API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)


class CodexUsageAdapter(UsagePort):
    BASE_URL = "https://chatgpt.com/backend-api/wham/usage"
    DEVICE_ID = "agentic-dev-gauge"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def provider_name(self) -> str:
        return "codex"

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    headers={
                        "authorization": f"Bearer {api_key}",
                        "oai-device-id": self.DEVICE_ID,
                        "user-agent": self.USER_AGENT,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Codex usage API error: %s", exc)
            return []

        if not isinstance(data, dict):
            logger.warning("Codex unexpected response type: %s", type(data).__name__)
            return []

        plan_type = data.get("plan_type")
        results: list[TokenUsage] = []

        rate_limit = data.get("rate_limit") or {}
        primary_window = rate_limit.get("primary_window") or {}
        secondary_window = rate_limit.get("secondary_window") or {}

        session_usage = self._build_usage(
            model="session",
            period="5h_rolling",
            window=primary_window,
            plan_type=plan_type,
        )
        if session_usage:
            results.append(session_usage)

        weekly_usage = self._build_usage(
            model="weekly",
            period="weekly",
            window=secondary_window,
            plan_type=plan_type,
        )
        if weekly_usage:
            results.append(weekly_usage)

        additional_limits = data.get("additional_rate_limits") or []
        if additional_limits:
            spark_window = ((additional_limits[0] or {}).get("rate_limit") or {}).get("secondary_window") or {}
            spark_usage = self._build_usage(
                model="spark-weekly",
                period="weekly",
                window=spark_window,
                plan_type=plan_type,
            )
            if spark_usage:
                results.append(spark_usage)

        review_window = (data.get("code_review_rate_limit") or {}).get("primary_window") or {}
        review_usage = self._build_usage(
            model="review",
            period="weekly",
            window=review_window,
            plan_type=plan_type,
        )
        if review_usage:
            results.append(review_usage)

        return results

    def _build_usage(
        self,
        *,
        model: str,
        period: str,
        window: dict,
        plan_type: str | None,
    ) -> TokenUsage | None:
        if not isinstance(window, dict):
            return None

        used_percent = window.get("used_percent")
        if used_percent is None:
            return None

        try:
            quota_percentage = float(used_percent)
        except (TypeError, ValueError):
            return None

        return TokenUsage(
            provider="codex",
            model=model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_usd=None,
            period=period,
            quota_percentage=quota_percentage,
            reset_text=self._format_reset(window.get("reset_at")),
            plan_type=plan_type,
        )

    def _format_reset(self, reset_at: object) -> str | None:
        if reset_at in (None, ""):
            return None

        try:
            if isinstance(reset_at, (int, float)):
                timestamp = float(reset_at)
                if timestamp > 1_000_000_000_000:
                    timestamp /= 1000
                reset_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            elif isinstance(reset_at, str):
                normalized = reset_at.replace("Z", "+00:00")
                reset_dt = datetime.fromisoformat(normalized)
                if reset_dt.tzinfo is None:
                    reset_dt = reset_dt.replace(tzinfo=timezone.utc)
                else:
                    reset_dt = reset_dt.astimezone(timezone.utc)
            else:
                return None
        except (TypeError, ValueError, OSError):
            logger.warning("Codex invalid reset_at value: %s", reset_at)
            return None

        return reset_dt.strftime("%Y-%m-%d %H:%M UTC")
