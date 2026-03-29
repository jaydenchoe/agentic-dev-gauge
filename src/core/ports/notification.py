"""Port interface for alert notifications."""

from abc import ABC, abstractmethod

from src.core.models import AlertEvent


class NotificationPort(ABC):
    @abstractmethod
    async def send_alert(self, event: AlertEvent) -> bool:
        """Send an alert notification. Return True on success."""
        ...
