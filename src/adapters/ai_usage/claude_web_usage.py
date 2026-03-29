"""Scrape Claude.ai /settings/usage page via Chrome DevTools Protocol (CDP).

Requires a Chrome instance running with --remote-debugging-port and the user
already logged in to claude.ai.
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

_CACHE_TTL = 120  # 2 minutes
_cache: dict[str, tuple[float, "ClaudeWebUsage"]] = {}


@dataclass
class ClaudeWebUsage:
    plan: str  # e.g. "맥스 플랜"
    session_used_percent: Optional[float] = None
    session_reset_text: Optional[str] = None
    weekly_all_used_percent: Optional[float] = None
    weekly_all_reset_text: Optional[str] = None
    weekly_sonnet_used_percent: Optional[float] = None
    weekly_sonnet_reset_text: Optional[str] = None
    extra_usage_usd: Optional[float] = None
    extra_usage_limit_usd: Optional[float] = None
    extra_usage_percent: Optional[float] = None
    extra_reset_text: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "plan": self.plan,
            "session": {
                "used_percent": self.session_used_percent,
                "reset_text": self.session_reset_text,
            },
            "weekly_all": {
                "used_percent": self.weekly_all_used_percent,
                "reset_text": self.weekly_all_reset_text,
            },
            "weekly_sonnet": {
                "used_percent": self.weekly_sonnet_used_percent,
                "reset_text": self.weekly_sonnet_reset_text,
            },
            "extra_usage": {
                "used_usd": self.extra_usage_usd,
                "limit_usd": self.extra_usage_limit_usd,
                "used_percent": self.extra_usage_percent,
                "reset_text": self.extra_reset_text,
            },
        }


async def fetch_claude_web_usage(
    cdp_host: str = "127.0.0.1",
    cdp_port: int = 9222,
) -> Optional[ClaudeWebUsage]:
    """Navigate to claude.ai/settings/usage via CDP and parse the page text."""
    cache_key = f"{cdp_host}:{cdp_port}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        # Find target page
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{cdp_host}:{cdp_port}/json")
            targets = resp.json()

        # Prefer a tab already on the usage page; fall back to any page tab
        usage_page = next(
            (t for t in targets if t["type"] == "page" and "claude.ai/settings/usage" in t.get("url", "")),
            None,
        )
        any_page = next(
            (t for t in targets if t["type"] == "page"),
            None,
        )
        page = usage_page or any_page
        if not page:
            logger.warning("No page target found on CDP %s:%s", cdp_host, cdp_port)
            return None

        ws_url = page["webSocketDebuggerUrl"]
        already_on_usage = usage_page is not None

        # Use websockets to connect
        text = await _cdp_get_page_text(ws_url, skip_navigate=already_on_usage)
        if not text:
            return None

        result = _parse_usage_text(text)
        if result:
            _cache[cache_key] = (time.time(), result)
        return result

    except Exception as exc:
        logger.warning("CDP claude web usage scrape failed: %s", exc)
        return None


async def _cdp_get_page_text(ws_url: str, skip_navigate: bool = False) -> Optional[str]:
    """Connect to CDP WebSocket, navigate to usage page, return innerText."""
    try:
        import websockets
    except ImportError:
        return await _cdp_get_page_text_raw(ws_url)

    async with websockets.connect(ws_url, max_size=2**22) as ws:
        if not skip_navigate:
            # Navigate to usage page only if not already there
            await ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": "https://claude.ai/settings/usage"},
            }))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == 1:
                    break
            # Wait for page to render
            await asyncio.sleep(6)
        else:
            # Already on usage page, just reload to get fresh data
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": "void 0"},
            }))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == 1:
                    break
            await asyncio.sleep(1)

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


async def _cdp_get_page_text_raw(ws_url: str) -> Optional[str]:
    """Fallback CDP via raw asyncio WebSocket (no websockets library)."""
    import subprocess
    import sys

    # Use Node.js ws from cheliped as fallback
    script = f"""
const WebSocket = require('ws');
const ws = new WebSocket('{ws_url}');
ws.on('open', () => {{
  ws.send(JSON.stringify({{id:1, method:'Page.navigate', params:{{url:'https://claude.ai/settings/usage'}}}}));
}});
ws.on('message', (msg) => {{
  const d = JSON.parse(msg);
  if (d.id === 1) {{
    setTimeout(() => {{
      ws.send(JSON.stringify({{id:2, method:'Runtime.evaluate', params:{{expression:'document.body.innerText'}}}}));
    }}, 6000);
  }}
  if (d.id === 2) {{
    console.log(JSON.stringify(d.result?.result?.value));
    ws.close();
    process.exit(0);
  }}
}});
setTimeout(() => process.exit(1), 20000);
"""
    cheliped_dir = f"{__import__('os').path.expanduser('~')}/.claude/skills/cheliped-browser/scripts"
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable.replace("python", "node").replace("python3", "node"),
            "-e", script,
            cwd=cheliped_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode().strip())
    except Exception as exc:
        logger.warning("Node.js CDP fallback failed: %s", exc)
    return None


def _parse_usage_text(text: str) -> Optional[ClaudeWebUsage]:
    """Parse the raw innerText from claude.ai/settings/usage."""
    if "보안 확인 수행 중" in text or "잠시만 기다리십시오" in text:
        logger.warning("Cloudflare challenge detected, cannot scrape")
        return None

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    usage = ClaudeWebUsage(plan="unknown")

    for i, line in enumerate(lines):
        # Plan name
        if "플랜" in line and ("맥스" in line or "프로" in line or "팀" in line or "무료" in line):
            usage.plan = line

        # Session usage
        if "현재 세션" in line:
            reset = _find_nearby(lines, i, "재설정")
            if reset:
                usage.session_reset_text = reset
            pct = _find_nearby(lines, i, "사용됨")
            if pct:
                usage.session_used_percent = _extract_percent(pct)

        # Weekly all models
        if "모든 모델" in line:
            reset = _find_nearby(lines, i, "재설정")
            if reset:
                usage.weekly_all_reset_text = reset
            pct = _find_nearby(lines, i, "사용됨")
            if pct:
                usage.weekly_all_used_percent = _extract_percent(pct)

        # Weekly sonnet only
        if "Sonnet만" in line or "Sonnet" in line and "만" in line:
            reset = _find_nearby(lines, i, "재설정")
            if reset:
                usage.weekly_sonnet_reset_text = reset
            pct = _find_nearby(lines, i, "사용됨")
            if pct:
                usage.weekly_sonnet_used_percent = _extract_percent(pct)

        # Extra usage
        if "추가 사용량" in line and i + 1 < len(lines):
            for j in range(i, min(i + 10, len(lines))):
                usd_match = re.search(r"US\$([0-9,.]+)\s*사용", lines[j])
                if usd_match:
                    usage.extra_usage_usd = float(usd_match.group(1).replace(",", ""))
                limit_match = re.search(r"US\$([0-9,.]+)$", lines[j])
                if limit_match and "한도" in lines[j - 1] if j > 0 else False:
                    usage.extra_usage_limit_usd = float(limit_match.group(1).replace(",", ""))
                pct_match = re.search(r"(\d+)%\s*사용", lines[j])
                if pct_match:
                    usage.extra_usage_percent = float(pct_match.group(1))

        # Extra usage limit line (월간 지출 한도)
        if "월간 지출 한도" in line:
            for j in range(max(0, i - 3), i):
                limit_match = re.search(r"US\$([0-9,.]+)", lines[j])
                if limit_match:
                    usage.extra_usage_limit_usd = float(limit_match.group(1).replace(",", ""))

    if usage.plan == "unknown" and not usage.session_used_percent:
        logger.warning("Failed to parse usage from page text")
        return None

    return usage


def _find_nearby(lines: list[str], idx: int, keyword: str, window: int = 5) -> Optional[str]:
    """Find a line containing keyword near the given index."""
    for j in range(idx, min(idx + window, len(lines))):
        if keyword in lines[j]:
            return lines[j]
    return None


def _extract_percent(text: str) -> Optional[float]:
    """Extract percentage number from text like '22% 사용됨'."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return float(match.group(1)) if match else None
