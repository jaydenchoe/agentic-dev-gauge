"""Fetch GitHub Copilot quota via the internal API.

Uses ``gh auth token`` to obtain a GitHub OAuth token, then queries
``https://api.github.com/copilot_internal/user`` for quota snapshots.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes
_cache: dict[str, tuple[float, "CopilotApiUsage"]] = {}


@dataclass
class CopilotQuota:
    quota_id: str  # "premium_interactions", "completions", "chat"
    entitlement: int
    remaining: int
    percent_remaining: float
    unlimited: bool

    @property
    def percent_used(self) -> float:
        return round(100.0 - self.percent_remaining, 1)


@dataclass
class CopilotApiUsage:
    plan: str  # "individual", "business", etc.
    quotas: list[CopilotQuota]
    reset_date: Optional[str] = None  # "2026-05-01"

    def to_dict(self) -> dict:
        return {
            "plan": self.plan,
            "reset_date": self.reset_date,
            "quotas": [
                {
                    "quota_id": q.quota_id,
                    "entitlement": q.entitlement,
                    "remaining": q.remaining,
                    "percent_used": q.percent_used,
                    "unlimited": q.unlimited,
                }
                for q in self.quotas
            ],
        }


async def _get_gh_token() -> Optional[str]:
    """Get GitHub token from gh CLI."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "auth", "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()
    except (FileNotFoundError, asyncio.TimeoutError):
        pass
    return None


async def fetch_copilot_api_usage(
    github_token: Optional[str] = None,
) -> Optional[CopilotApiUsage]:
    """Fetch Copilot quota from GitHub internal API."""
    cache_key = "copilot_api"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    token = github_token or await _get_gh_token()
    if not token:
        logger.warning("No GitHub token available for Copilot API")
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.github.com/copilot_internal/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "TinyMonitor/1.0",
                },
            )
            if resp.status_code != 200:
                logger.warning("Copilot API returned %s: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
    except Exception as exc:
        logger.warning("Copilot API request failed: %s", exc)
        return None

    plan = data.get("copilot_plan", "unknown")
    reset_date = data.get("quota_reset_date")
    snapshots = data.get("quota_snapshots", {})

    quotas: list[CopilotQuota] = []
    for quota_id, snap in snapshots.items():
        quotas.append(CopilotQuota(
            quota_id=quota_id,
            entitlement=snap.get("entitlement", 0),
            remaining=snap.get("remaining", 0),
            percent_remaining=snap.get("percent_remaining", 100.0),
            unlimited=snap.get("unlimited", False),
        ))

    result = CopilotApiUsage(plan=plan, quotas=quotas, reset_date=reset_date)
    _cache[cache_key] = (time.time(), result)
    return result
