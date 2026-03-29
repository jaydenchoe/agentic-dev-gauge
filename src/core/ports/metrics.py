"""Port interface for system metrics collection."""

from abc import ABC, abstractmethod

from src.core.models import SystemSnapshot


class MetricsPort(ABC):
    @abstractmethod
    async def collect(self) -> SystemSnapshot:
        """Collect system metrics and return a SystemSnapshot."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Return whether this adapter is usable in the current environment."""
        ...
