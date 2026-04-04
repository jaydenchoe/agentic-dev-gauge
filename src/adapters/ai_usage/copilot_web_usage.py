"""Scrape GitHub Copilot premium requests usage via Chrome DevTools Protocol (CDP).

Requires a Chrome instance running with --remote-debugging-port and the user
already logged in to github.com.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes
_cache: dict[str, tuple[float, "CopilotWebUsage"]] = {}

_COPILOT_URL = "https://github.com/settings/copilot/features"


@dataclass
class CopilotWebUsage:
    premium_used_percent: Optional[float] = None
    plan: Optional[str] = None  # e.g. "Pro"
    reset_text: Optional[str] = None  # e.g. "start of next month"

    def to_dict(self) -> dict:
        return {
            "premium_used_percent": self.premium_used_percent,
            "plan": self.plan,
            "reset_text": self.reset_text,
        }


async def fetch_copilot_web_usage(
    cdp_host: str = "127.0.0.1",
    cdp_port: int = 9222,
) -> Optional[CopilotWebUsage]:
    """Navigate to GitHub Copilot settings via CDP and parse premium requests usage."""
    cache_key = f"copilot:{cdp_host}:{cdp_port}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{cdp_host}:{cdp_port}/json")
            targets = resp.json()

        # Find existing GitHub Copilot tab
        copilot_page = next(
            (t for t in targets if t["type"] == "page" and "github.com/settings/copilot" in t.get("url", "")),
            None,
        )

        if copilot_page:
            ws_url = copilot_page["webSocketDebuggerUrl"]
            text = await _cdp_get_page_text(ws_url, skip_navigate=True)
        else:
            # Open new tab
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(
                    f"http://{cdp_host}:{cdp_port}/json/new?{_COPILOT_URL}"
                )
                tab = resp.json()
                ws_url = tab["webSocketDebuggerUrl"]
                tab_id = tab["id"]

            text = await _cdp_get_page_text(ws_url, skip_navigate=False, is_new_tab=True)

            # Close the tab after scraping
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(f"http://{cdp_host}:{cdp_port}/json/close/{tab_id}")

        if not text:
            return None

        result = _parse_copilot_text(text)
        if result:
            _cache[cache_key] = (time.time(), result)
        return result

    except Exception as exc:
        logger.warning("CDP copilot web usage scrape failed: %s", exc)
        return None


async def _cdp_get_page_text(
    ws_url: str,
    skip_navigate: bool = False,
    is_new_tab: bool = False,
) -> Optional[str]:
    """Connect to CDP WebSocket and return page innerText."""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets library not available for Copilot CDP scraping")
        return None

    async with websockets.connect(ws_url, max_size=2**22) as ws:
        if is_new_tab:
            # New tab already navigated via /json/new, just wait for load
            await asyncio.sleep(8)
        elif not skip_navigate:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": _COPILOT_URL},
            }))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == 1:
                    break
            await asyncio.sleep(8)
        else:
            # Already on copilot page — reload to get fresh data
            await ws.send(json.dumps({
                "id": 1,
                "method": "Page.reload",
                "params": {},
            }))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == 1:
                    break
            await asyncio.sleep(6)

        # Extract text
        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.body.innerText"},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("id") == 2:
                return msg.get("result", {}).get("result", {}).get("value")

    return None


def _parse_copilot_text(text: str) -> Optional[CopilotWebUsage]:
    """Parse the raw innerText from GitHub Copilot settings page."""
    if not text:
        return None

    # Check for login/auth wall
    if "Two-factor authentication" in text or "Sign in" in text:
        logger.warning("GitHub login required, cannot scrape Copilot usage")
        return None

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    usage = CopilotWebUsage()

    for i, line in enumerate(lines):
        # Detect plan: "GitHub Copilot Pro is active" or similar
        plan_match = re.search(r"Copilot\s+(Pro|Business|Enterprise|Individual|Free)", line, re.IGNORECASE)
        if plan_match:
            usage.plan = plan_match.group(1)

        # Premium requests percentage — look for the line after "Premium requests"
        if "Premium requests" in line:
            # The percentage is typically the next non-empty line
            for j in range(i + 1, min(i + 5, len(lines))):
                pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", lines[j])
                if pct_match:
                    usage.premium_used_percent = float(pct_match.group(1))
                    break

        # Reset text — extract just the reset timing
        if "reset" in line.lower() and "start of next month" in line.lower():
            usage.reset_text = "Resets at start of next month"

    if usage.premium_used_percent is None:
        logger.warning("Failed to parse Copilot premium requests from page text")
        return None

    return usage
