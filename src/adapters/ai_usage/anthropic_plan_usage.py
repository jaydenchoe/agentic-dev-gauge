"""Query Anthropic session (5h rolling) and weekly token usage via Admin API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.anthropic.com/v1/organizations"
_MAX_PAGES = 20
_CACHE_TTL = 300  # cache results for 5 minutes
_cache: dict[str, tuple[float, "PlanUsage"]] = {}


@dataclass
class PlanUsage:
    session_tokens: int          # tokens used in last 5 hours
    session_limit: Optional[int] # user-configured limit
    session_percent: Optional[float]
    weekly_tokens: int           # tokens used in last 7 days
    weekly_limit: Optional[int]
    weekly_percent: Optional[float]
    session_window_hours: int = 5

    def to_dict(self) -> dict:
        return {
            "session": {
                "used_tokens": self.session_tokens,
                "limit_tokens": self.session_limit,
                "used_percent": self.session_percent,
                "window_hours": self.session_window_hours,
            },
            "weekly": {
                "used_tokens": self.weekly_tokens,
                "limit_tokens": self.weekly_limit,
                "used_percent": self.weekly_percent,
            },
        }


async def fetch_plan_usage(
    admin_key: str,
    session_limit: Optional[int] = None,
    weekly_limit: Optional[int] = None,
) -> Optional[PlanUsage]:
    """Fetch token usage for the last 5 hours and 7 days. Cached for 5 min."""
    cache_key = admin_key[:10]
    cached = _cache.get(cache_key)
    if cached:
        ts, prev = cached
        if time.time() - ts < _CACHE_TTL:
            # Update limits from current settings (may have changed)
            prev.session_limit = session_limit
            prev.session_percent = round(prev.session_tokens / session_limit * 100, 1) if session_limit else None
            prev.weekly_limit = weekly_limit
            prev.weekly_percent = round(prev.weekly_tokens / weekly_limit * 100, 1) if weekly_limit else None
            return prev

    now = datetime.now(timezone.utc)
    five_h_ago = now - timedelta(hours=5)
    seven_d_ago = now - timedelta(days=7)

    try:
        from src.adapters.ai_usage.anthropic_throttle import throttle
        await throttle()
        async with httpx.AsyncClient(timeout=30.0) as client:
            session_tokens = await _sum_tokens(client, admin_key, five_h_ago, now)
            await throttle()
            weekly_tokens = await _sum_tokens(client, admin_key, seven_d_ago, now)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.info("Anthropic plan usage: rate limited, using cache")
        else:
            logger.warning("Anthropic plan usage fetch failed: %s", exc.response.status_code)
        if cached:
            return cached[1]
        return None
    except httpx.HTTPError as exc:
        logger.warning("Anthropic plan usage fetch failed: %s", exc)
        if cached:
            return cached[1]
        return None

    session_pct = round(session_tokens / session_limit * 100, 1) if session_limit else None
    weekly_pct = round(weekly_tokens / weekly_limit * 100, 1) if weekly_limit else None

    result = PlanUsage(
        session_tokens=session_tokens,
        session_limit=session_limit,
        session_percent=session_pct,
        weekly_tokens=weekly_tokens,
        weekly_limit=weekly_limit,
        weekly_percent=weekly_pct,
    )
    _cache[cache_key] = (time.time(), result)
    return result


async def _sum_tokens(
    client: httpx.AsyncClient,
    admin_key: str,
    start: datetime,
    end: datetime,
) -> int:
    """Sum all input+output tokens in the given time range, handling pagination."""
    headers = {"x-api-key": admin_key, "anthropic-version": "2023-06-01"}
    total = 0
    next_page: Optional[str] = None

    for _ in range(_MAX_PAGES):
        params: list[tuple[str, str]] = [
            ("starting_at", start.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("ending_at", end.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
        if next_page:
            params.append(("page", next_page))

        resp = await client.get(
            f"{BASE_URL}/usage_report/messages",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                total += result.get("input_tokens", 0)
                total += result.get("output_tokens", 0)

        if not data.get("has_more"):
            break
        next_page = data.get("next_page")
        if not next_page:
            break

    return total
