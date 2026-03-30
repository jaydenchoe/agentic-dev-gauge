"""GeminiUsageAdapter — session-level token accumulation for Google Gemini.

Gemini does not provide an official usage-reporting endpoint.  This adapter
tracks tokens accumulated within the application lifetime and exposes them
through the standard UsagePort interface.
"""

from __future__ import annotations

import logging

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)


class GeminiUsageAdapter(UsagePort):
    """In-process token accumulator for Gemini API calls."""

    def __init__(self) -> None:
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def provider_name(self) -> str:
        return "gemini"

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Call after each Gemini API response to accumulate usage."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        total = self._input_tokens + self._output_tokens
        if total == 0:
            return []
        return [
            TokenUsage(
                provider="gemini",
                model="gemini",
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=total,
                cost_usd=None,
                period="session",
            )
        ]
