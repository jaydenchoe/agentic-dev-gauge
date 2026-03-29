"""Global throttle for all Anthropic Admin API calls."""

import asyncio
import time

_MIN_INTERVAL = 10.0  # minimum seconds between API calls
_last_call: float = 0.0
_lock = asyncio.Lock()


async def throttle() -> None:
    """Wait if needed to respect rate limits."""
    global _last_call
    async with _lock:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.time()
