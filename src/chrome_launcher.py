"""Launch a Chrome instance with a dedicated debug profile for CDP scraping."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _find_chrome_binary() -> Optional[str]:
    """Find Chrome/Chromium binary on the current platform."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]
    else:
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


async def _is_cdp_alive(host: str, port: int) -> bool:
    """Check if a CDP endpoint is already responding."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{host}:{port}/json/version")
            return resp.status_code == 200
    except Exception:
        return False


def launch_dashboard_app(url: str = "http://localhost:8080") -> Optional[subprocess.Popen]:
    """Launch Chrome in --app mode (no address bar) for the dashboard."""
    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        logger.warning("Chrome binary not found, cannot launch dashboard app")
        return None

    try:
        proc = subprocess.Popen(
            [chrome_bin, f"--app={url}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Dashboard app launched (PID %d): %s", proc.pid, url)
        return proc
    except Exception as exc:
        logger.error("Failed to launch dashboard app: %s", exc)
        return None


async def launch_debug_chrome(
    profile_dir: str,
    port: int = 9222,
) -> Optional[subprocess.Popen]:
    """Launch Chrome with a dedicated debug profile.

    Returns the Popen handle if launched, None if already running or unavailable.
    """
    # Expand ~ in profile path
    profile_path = Path(profile_dir).expanduser()
    profile_path.mkdir(parents=True, exist_ok=True)

    # Check if CDP is already available
    if await _is_cdp_alive("127.0.0.1", port):
        logger.info("CDP already available on port %d, skipping Chrome launch", port)
        return None

    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        logger.warning("Chrome binary not found, cannot launch debug instance")
        return None

    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://claude.ai/settings/usage",
    ]

    logger.info("Launching debug Chrome: port=%d, profile=%s", port, profile_path)
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait a bit for Chrome to start
        await asyncio.sleep(2)

        if await _is_cdp_alive("127.0.0.1", port):
            logger.info("Debug Chrome launched successfully (PID %d)", proc.pid)
            return proc
        else:
            logger.warning("Debug Chrome launched but CDP not responding yet")
            return proc
    except Exception as exc:
        logger.error("Failed to launch debug Chrome: %s", exc)
        return None


def shutdown_debug_chrome(proc: Optional[subprocess.Popen]) -> None:
    """Gracefully terminate the debug Chrome process."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
        logger.info("Debug Chrome terminated (PID %d)", proc.pid)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning("Debug Chrome killed (PID %d)", proc.pid)
    except Exception:
        pass
