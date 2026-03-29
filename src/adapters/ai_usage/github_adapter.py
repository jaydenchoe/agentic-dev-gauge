"""CopilotUsageAdapter — fetch GitHub Copilot usage via GitHub REST API."""

from __future__ import annotations

import logging

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)


class CopilotUsageAdapter(UsagePort):
    """GitHub Copilot usage.

    Org-level usage is available via the REST API.  For personal accounts the
    API surface is limited, so we return a zero-usage placeholder.
    """

    def __init__(self, org: str | None = None) -> None:
        self._org = org

    def provider_name(self) -> str:
        return "github"

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        if not self._org:
            return [
                TokenUsage(
                    provider="github",
                    model="copilot",
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    cost_usd=None,
                    period="current_month",
                )
            ]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://api.github.com/orgs/{self._org}/copilot/usage",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("GitHub Copilot usage API error: %s", exc)
            return []

        total_completions = sum(d.get("total_completions", 0) for d in data)
        return [
            TokenUsage(
                provider="github",
                model="copilot",
                input_tokens=0,
                output_tokens=total_completions,
                total_tokens=total_completions,
                cost_usd=None,
                period="current_month",
            )
        ]
