"""OpenClawNotifier — send alert notifications to OpenClaw Gateway."""

from __future__ import annotations

import logging

import httpx

from src.core.models import AlertEvent
from src.core.ports.notification import NotificationPort

logger = logging.getLogger(__name__)


class OpenClawNotifier(NotificationPort):
    """POST alert messages to the OpenClaw Gateway HTTP endpoint."""

    def __init__(self, gateway_url: str, api_key: str | None = None) -> None:
        self._url = gateway_url.rstrip("/") + "/api/sessions/main/messages"
        self._api_key = api_key

    async def send_alert(self, event: AlertEvent) -> bool:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        message = (
            f"[Tiny Monitor] {event.level.upper()}: "
            f"{event.metric} = {event.current_value:.1f} "
            f"(threshold {event.threshold:.1f}) — {event.message}"
        )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._url,
                    headers=headers,
                    json={"message": message},
                )
                if resp.status_code == 200:
                    return True
                logger.warning(
                    "OpenClaw Gateway returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except httpx.HTTPError as exc:
            logger.warning("OpenClaw Gateway request failed: %s", exc)
            return False
