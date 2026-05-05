"""WebSocket endpoint for real-time metric streaming."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialise(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialise(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialise(i) for i in obj]
    return obj


class ConnectionManager:
    """Manages active WebSocket connections and their channel subscriptions."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        # Subscribe to all channels by default
        self._connections[ws] = {"system_metrics", "usage_update", "alert"}

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    def subscribe(self, ws: WebSocket, channels: list[str]) -> None:
        if ws in self._connections:
            self._connections[ws] = set(channels)

    async def broadcast(self, channel: str, data: Any) -> None:
        message = json.dumps({
            "type": channel,
            "data": _serialise(data),
        })
        dead: list[WebSocket] = []
        for ws, channels in self._connections.items():
            if channel not in channels:
                continue
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=5.0)
            except asyncio.TimeoutError:
                dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "subscribe" and isinstance(msg.get("channels"), list):
                manager.subscribe(ws, msg["channels"])
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


async def run_broadcast_loop(app: Any) -> None:
    """Background task: periodically broadcasts metrics and usage to all WS clients."""
    monitor_svc = app.state.monitor_service
    usage_svc = app.state.usage_service
    alert_svc = app.state.alert_service
    settings = app.state.settings

    metrics_interval = settings.metrics_interval_sec
    usage_interval = settings.usage_interval_sec
    usage_counter = 0

    while True:
        # System metrics
        snapshot = monitor_svc.latest
        if snapshot and manager.active_count > 0:
            try:
                await manager.broadcast("system_metrics", snapshot)
            except Exception:
                pass

            # Check thresholds and broadcast alerts
            alerts = await alert_svc.check_system(snapshot)
            for alert in alerts:
                try:
                    await manager.broadcast("alert", alert)
                except Exception:
                    pass

        # Usage (less frequent)
        usage_counter += metrics_interval
        if usage_counter >= usage_interval:
            usage_counter = 0
            usage_snapshot = usage_svc.latest
            claude_web = usage_svc.claude_web_latest
            copilot_api = usage_svc.copilot_api_latest
            ollama = usage_svc.ollama_latest
            lm_studio = usage_svc.lm_studio_latest
            if manager.active_count > 0 and (usage_snapshot or claude_web or copilot_api or ollama or lm_studio):
                usage_data = _serialise(usage_snapshot) if usage_snapshot else {}
                usage_data["claude_web"] = claude_web.to_dict() if claude_web else None
                usage_data["copilot_api"] = copilot_api.to_dict() if copilot_api else None
                usage_data["ollama"] = ollama.to_dict() if ollama else None
                usage_data["lm_studio"] = lm_studio.to_dict() if lm_studio else None
                try:
                    await manager.broadcast("usage_update", usage_data)
                except Exception:
                    pass

                if usage_snapshot:
                    cost_alerts = await alert_svc.check_usage(usage_snapshot)
                    for alert in cost_alerts:
                        try:
                            await manager.broadcast("alert", alert)
                        except Exception:
                            pass


        await asyncio.sleep(metrics_interval)
