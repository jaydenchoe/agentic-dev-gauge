"""Port interface for external display push adapters."""

from abc import ABC, abstractmethod


class DisplayPort(ABC):
    @abstractmethod
    async def push_png(self, png_bytes: bytes) -> bool:
        """Send a rendered PNG image to the display. Return True on success."""
        ...
