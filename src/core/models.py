"""Tiny Monitor domain models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CpuMetrics:
    usage_percent: float
    per_core: list[float]
    frequency_mhz: Optional[float] = None
    temperature_celsius: Optional[float] = None


@dataclass
class MemoryMetrics:
    total_gb: float
    used_gb: float
    available_gb: float
    usage_percent: float


@dataclass
class DiskMetrics:
    total_gb: float
    used_gb: float
    free_gb: float
    usage_percent: float
    read_bytes_per_sec: float
    write_bytes_per_sec: float


@dataclass
class NetworkMetrics:
    bytes_sent_per_sec: float
    bytes_recv_per_sec: float


@dataclass
class GpuMetrics:
    usage_percent: float
    memory_used_mb: float
    memory_total_mb: float
    temperature_celsius: Optional[float] = None


@dataclass
class SystemSnapshot:
    timestamp: datetime
    cpu: CpuMetrics
    memory: MemoryMetrics
    disk: DiskMetrics
    network: NetworkMetrics
    gpu: Optional[GpuMetrics] = None


@dataclass
class TokenUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Optional[float] = None
    period: str = "current_month"
    quota_limit: Optional[int] = None


@dataclass
class UsageSnapshot:
    timestamp: datetime
    usages: list[TokenUsage]
    total_cost_usd: Optional[float] = None


@dataclass
class ThresholdConfig:
    metric: str
    warning: float
    critical: float


@dataclass
class AlertEvent:
    timestamp: datetime
    metric: str
    current_value: float
    threshold: float
    level: str
    message: str
