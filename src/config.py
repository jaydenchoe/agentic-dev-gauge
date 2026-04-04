"""Application settings loaded from environment / .env file."""

from __future__ import annotations

import json
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

from src.core.models import ThresholdConfig


_DEFAULT_THRESHOLDS = [
    {"metric": "cpu_percent", "warning": 80, "critical": 95},
    {"metric": "memory_percent", "warning": 80, "critical": 95},
    {"metric": "disk_percent", "warning": 85, "critical": 95},
    {"metric": "token_cost", "warning": 10.0, "critical": 50.0},
    {"metric": "llm_usage_percent", "warning": 80, "critical": 90},
]


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # Metrics
    metrics_interval_sec: float = 2
    metrics_backend: str = "auto"  # auto | psutil | macmon

    # AI Usage API Keys (all optional)
    zhipuai_api_key: Optional[str] = None

    # Usage polling
    usage_interval_sec: float = 60

    # Claude web usage (CDP scraping)
    claude_web_cdp_port: int = 9222
    claude_web_interval_sec: float = 300  # 5 minutes

    # Copilot API usage
    copilot_api_interval_sec: float = 300  # 5 minutes

    # Chrome debug profile for CDP scraping
    chrome_debug_profile_dir: str = "~/.tiny-monitor/chrome-debug-profile"
    chrome_debug_port: int = 9222
    chrome_debug_auto_launch: bool = True  # auto-launch debug Chrome on startup


    @field_validator(
        "zhipuai_api_key",
        "openclaw_gateway_url", "openclaw_api_key",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # Thresholds
    thresholds: list[ThresholdConfig] = [
        ThresholdConfig(**t) for t in _DEFAULT_THRESHOLDS
    ]

    # OpenClaw Gateway (optional)
    openclaw_gateway_url: Optional[str] = None
    openclaw_api_key: Optional[str] = None

    @field_validator("thresholds", mode="before")
    @classmethod
    def parse_thresholds(cls, v: object) -> list[dict]:
        if isinstance(v, str):
            items = json.loads(v)
            return [ThresholdConfig(**t) if isinstance(t, dict) else t for t in items]
        return v  # type: ignore[return-value]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
