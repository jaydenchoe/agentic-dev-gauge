"""OpenClawUsageAdapter — parse ``openclaw status --usage --json`` output."""

from __future__ import annotations

import asyncio
import json
import logging

from src.core.models import TokenUsage

logger = logging.getLogger(__name__)

_CLI_TIMEOUT = 10.0


class OpenClawUsageAdapter:
    """Retrieve aggregated AI usage from the local OpenClaw CLI.

    This is *not* a UsagePort implementation because it returns data for
    multiple providers at once.  The service layer can use it as a fallback
    or supplement to per-provider adapters.
    """

    async def fetch_all_usage(self) -> list[TokenUsage]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "openclaw", "status", "--usage", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_CLI_TIMEOUT)
            data = json.loads(stdout)
        except FileNotFoundError:
            logger.debug("openclaw CLI not found — skipping")
            return []
        except asyncio.TimeoutError:
            logger.warning("openclaw CLI timed out")
            return []
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("openclaw parse error: %s", exc)
            return []

        return [self._parse_service(s) for s in data.get("services", [])]

    @staticmethod
    def _parse_service(service: dict) -> TokenUsage:
        used = service.get("used_tokens", 0)
        return TokenUsage(
            provider=service.get("name", "unknown"),
            model=service.get("model", "unknown"),
            input_tokens=used,
            output_tokens=0,
            total_tokens=used,
            cost_usd=service.get("used_cost_usd"),
            period=service.get("period", "monthly"),
        )
