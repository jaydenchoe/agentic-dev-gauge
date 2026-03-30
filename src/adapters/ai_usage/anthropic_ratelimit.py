"""Check Anthropic plan usage via rate-limit headers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RateLimitInfo:
    requests_limit: int
    requests_remaining: int
    requests_reset: str
    tokens_limit: int
    tokens_remaining: int
    tokens_reset: str
    input_tokens_limit: Optional[int] = None
    input_tokens_remaining: Optional[int] = None
    input_tokens_reset: Optional[str] = None
    output_tokens_limit: Optional[int] = None
    output_tokens_remaining: Optional[int] = None
    output_tokens_reset: Optional[str] = None

    @property
    def requests_used_percent(self) -> float:
        if self.requests_limit == 0:
            return 0.0
        used = self.requests_limit - self.requests_remaining
        return round(used / self.requests_limit * 100, 1)

    @property
    def tokens_used_percent(self) -> float:
        if self.tokens_limit == 0:
            return 0.0
        used = self.tokens_limit - self.tokens_remaining
        return round(used / self.tokens_limit * 100, 1)

    def to_dict(self) -> dict:
        return {
            "requests": {
                "limit": self.requests_limit,
                "remaining": self.requests_remaining,
                "used": self.requests_limit - self.requests_remaining,
                "used_percent": self.requests_used_percent,
                "reset": self.requests_reset,
            },
            "tokens": {
                "limit": self.tokens_limit,
                "remaining": self.tokens_remaining,
                "used": self.tokens_limit - self.tokens_remaining,
                "used_percent": self.tokens_used_percent,
                "reset": self.tokens_reset,
            },
        }


async def fetch_anthropic_rate_limits(api_key: str) -> Optional[RateLimitInfo]:
    """Make a minimal messages call (max_tokens=1) to read rate-limit headers."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
            )
            # Even 4xx responses include rate-limit headers
            h = resp.headers
            return RateLimitInfo(
                requests_limit=int(h.get("anthropic-ratelimit-requests-limit", 0)),
                requests_remaining=int(h.get("anthropic-ratelimit-requests-remaining", 0)),
                requests_reset=h.get("anthropic-ratelimit-requests-reset", ""),
                tokens_limit=int(h.get("anthropic-ratelimit-tokens-limit", 0)),
                tokens_remaining=int(h.get("anthropic-ratelimit-tokens-remaining", 0)),
                tokens_reset=h.get("anthropic-ratelimit-tokens-reset", ""),
                input_tokens_limit=_int_or_none(h.get("anthropic-ratelimit-input-tokens-limit")),
                input_tokens_remaining=_int_or_none(h.get("anthropic-ratelimit-input-tokens-remaining")),
                input_tokens_reset=h.get("anthropic-ratelimit-input-tokens-reset"),
                output_tokens_limit=_int_or_none(h.get("anthropic-ratelimit-output-tokens-limit")),
                output_tokens_remaining=_int_or_none(h.get("anthropic-ratelimit-output-tokens-remaining")),
                output_tokens_reset=h.get("anthropic-ratelimit-output-tokens-reset"),
            )
    except Exception as exc:
        logger.warning("Anthropic rate-limit check failed: %s", exc)
        return None


def _int_or_none(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None
