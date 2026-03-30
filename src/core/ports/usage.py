"""Port interface for AI token usage retrieval."""

from abc import ABC, abstractmethod

from src.core.models import TokenUsage


class UsagePort(ABC):
    @abstractmethod
    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        """Fetch token usage data using the given API key."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g. 'anthropic')."""
        ...
