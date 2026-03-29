"""Checks thresholds against current metrics/usage and fires alerts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.core.models import AlertEvent, SystemSnapshot, ThresholdConfig, UsageSnapshot
from src.core.ports.notification import NotificationPort

logger = logging.getLogger(__name__)

# Suppress duplicate alerts within this window (seconds).
ALERT_COOLDOWN_SEC = 300


class AlertService:
    def __init__(
        self,
        thresholds: list[ThresholdConfig],
        notifier: Optional[NotificationPort] = None,
    ) -> None:
        self._thresholds = {t.metric: t for t in thresholds}
        self._notifier = notifier
        self._recent_alerts: list[AlertEvent] = []
        # metric -> last alert timestamp (for cooldown)
        self._last_fired: dict[str, datetime] = {}

    @property
    def recent_alerts(self) -> list[AlertEvent]:
        return list(self._recent_alerts[-50:])

    def update_thresholds(self, thresholds: list[ThresholdConfig]) -> None:
        self._thresholds = {t.metric: t for t in thresholds}

    async def check_system(self, snapshot: SystemSnapshot) -> list[AlertEvent]:
        values: dict[str, float] = {
            "cpu_percent": snapshot.cpu.usage_percent,
            "memory_percent": snapshot.memory.usage_percent,
            "disk_percent": snapshot.disk.usage_percent,
        }
        alerts: list[AlertEvent] = []
        now = datetime.now(timezone.utc)

        for metric, value in values.items():
            cfg = self._thresholds.get(metric)
            if cfg is None:
                continue
            alert = self._evaluate(metric, value, cfg, now)
            if alert:
                alerts.append(alert)

        return alerts

    async def check_usage(self, snapshot: UsageSnapshot) -> list[AlertEvent]:
        if snapshot.total_cost_usd is None:
            return []
        cfg = self._thresholds.get("token_cost")
        if cfg is None:
            return []
        now = datetime.now(timezone.utc)
        alert = self._evaluate("token_cost", snapshot.total_cost_usd, cfg, now)
        return [alert] if alert else []

    def _evaluate(
        self,
        metric: str,
        value: float,
        cfg: ThresholdConfig,
        now: datetime,
    ) -> Optional[AlertEvent]:
        if value >= cfg.critical:
            level, threshold = "critical", cfg.critical
        elif value >= cfg.warning:
            level, threshold = "warning", cfg.warning
        else:
            return None

        # Cooldown check
        last = self._last_fired.get(metric)
        if last and (now - last).total_seconds() < ALERT_COOLDOWN_SEC:
            return None

        event = AlertEvent(
            timestamp=now,
            metric=metric,
            current_value=value,
            threshold=threshold,
            level=level,
            message=f"{metric} is {value:.1f} — exceeds {level} threshold ({threshold})",
        )
        self._last_fired[metric] = now
        self._recent_alerts.append(event)
        asyncio.create_task(self._notify(event))
        return event

    async def _notify(self, event: AlertEvent) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.send_alert(event)
        except Exception:
            logger.exception("Failed to send alert notification")
