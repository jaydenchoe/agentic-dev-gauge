---
name: backend-impl
description: "Tiny Monitor 백엔드 구현 가이드. FastAPI + Hexagonal Architecture 기반 서버, WebSocket 실시간 스트리밍, 서비스 레이어, 알림 엔진 구현 방법을 안내한다. backend-dev 에이전트가 참조하는 스킬."
---

# Backend Implementation Guide

## 프로젝트 구조

```
src/
├── main.py                 # FastAPI 앱, 라이프사이클, 미들웨어
├── config.py               # Pydantic Settings, .env 로드
├── core/
│   ├── __init__.py
│   ├── models.py           # 도메인 모델 (dataclass)
│   └── ports/
│       ├── __init__.py
│       ├── metrics.py      # MetricsPort ABC
│       ├── usage.py        # UsagePort ABC
│       └── notification.py # NotificationPort ABC
├── services/
│   ├── __init__.py
│   ├── metrics_service.py  # 시스템 메트릭 수집/캐싱
│   ├── usage_service.py    # AI 사용량 수집/캐싱
│   └── alert_service.py    # Threshold 체크 + 알림 발송
├── api/
│   ├── __init__.py
│   ├── routes.py           # REST 엔드포인트
│   └── websocket.py        # WebSocket 엔드포인트
└── adapters/               # adapter-dev가 구현
```

## 도메인 모델 (core/models.py)

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class MetricStatus(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class SystemMetrics:
    cpu_percent: float
    ram_used_gb: float
    ram_total_gb: float
    disk_used_gb: float
    disk_total_gb: float
    gpu_percent: float | None = None
    npu_power_w: float | None = None
    temperature_c: float | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass
class AIServiceUsage:
    service_name: str           # "claude_opus", "claude_sonnet", "openai", etc.
    used_tokens: int
    limit_tokens: int | None    # None이면 종량제 (한도 없음)
    used_cost_usd: float | None
    limit_cost_usd: float | None
    period: str                 # "daily", "monthly"
    last_updated: datetime = field(default_factory=datetime.utcnow)

@dataclass
class AlertConfig:
    metric_name: str            # "cpu", "ram", "claude_opus", etc.
    warning_threshold: float    # 0.0 ~ 1.0 (퍼센트)
    critical_threshold: float
    notify_openclaw: bool = True

@dataclass
class Alert:
    metric_name: str
    current_value: float
    threshold: float
    status: MetricStatus
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

## Port 인터페이스 (core/ports/)

```python
# metrics.py
from abc import ABC, abstractmethod
from core.models import SystemMetrics

class MetricsPort(ABC):
    @abstractmethod
    async def get_system_metrics(self) -> SystemMetrics: ...

# usage.py
from abc import ABC, abstractmethod
from core.models import AIServiceUsage

class UsagePort(ABC):
    @abstractmethod
    async def get_usage(self) -> AIServiceUsage: ...

    @abstractmethod
    def service_name(self) -> str: ...

# notification.py
from abc import ABC, abstractmethod
from core.models import Alert

class NotificationPort(ABC):
    @abstractmethod
    async def send_alert(self, alert: Alert) -> bool: ...
```

## REST API 엔드포인트

| 메서드 | 경로 | 설명 | 응답 |
|--------|------|------|------|
| GET | `/api/metrics` | 현재 시스템 메트릭 | SystemMetrics JSON |
| GET | `/api/usage` | 모든 AI 서비스 사용량 | AIServiceUsage[] JSON |
| GET | `/api/usage/{service}` | 특정 서비스 사용량 | AIServiceUsage JSON |
| GET | `/api/alerts` | 현재 활성 알림 | Alert[] JSON |
| GET | `/api/config` | 현재 설정 | Config JSON |
| PUT | `/api/config` | 설정 업데이트 | Config JSON |
| POST | `/api/config/apikeys` | API 키 저장 | 성공/실패 |
| GET | `/api/license` | 라이선스 상태 | { tier: "free"|"pro", valid: bool } |
| POST | `/api/license/verify` | 라이선스 키 검증 | { valid: bool } |
| WS | `/ws/live` | 실시간 메트릭 스트림 | — |

## WebSocket 메시지 포맷

```json
{
  "type": "metrics" | "usage" | "alert",
  "data": { ... },
  "timestamp": "2026-03-28T12:00:00Z"
}
```

### metrics 메시지 (1초 간격)
```json
{
  "type": "metrics",
  "data": {
    "cpu_percent": 45.2,
    "ram_used_gb": 12.4,
    "ram_total_gb": 32.0,
    "disk_used_gb": 234.5,
    "disk_total_gb": 500.0,
    "gpu_percent": 30.1,
    "npu_power_w": 2.5,
    "temperature_c": 62.0
  },
  "timestamp": "2026-03-28T12:00:00Z"
}
```

### usage 메시지 (5분 간격)
```json
{
  "type": "usage",
  "data": [
    {
      "service_name": "claude_opus",
      "used_tokens": 1500000,
      "limit_tokens": 5000000,
      "used_cost_usd": 7.50,
      "limit_cost_usd": null,
      "period": "monthly"
    }
  ],
  "timestamp": "2026-03-28T12:00:00Z"
}
```

### alert 메시지 (발생 시 즉시)
```json
{
  "type": "alert",
  "data": {
    "metric_name": "ram",
    "current_value": 0.92,
    "threshold": 0.90,
    "status": "critical",
    "message": "RAM 사용량 92% - 임계값 90% 초과"
  },
  "timestamp": "2026-03-28T12:00:00Z"
}
```

## 서비스 레이어 구현 가이드

### MetricsService
- MetricsPort를 주입받아 주기적으로 메트릭 수집 (asyncio.Task)
- 수집 주기: 1초
- 최근 60개 데이터 포인트 캐시 (1분 히스토리)

### UsageService
- 여러 UsagePort를 리스트로 주입받아 각 서비스 사용량 수집
- 수집 주기: 5분 (API rate limit 고려)
- 캐시 + last_updated 타임스탬프 관리

### AlertService
- MetricsService/UsageService의 데이터를 감시
- AlertConfig 기반 threshold 체크
- 초과 시 NotificationPort로 알림 발송
- 중복 알림 방지: 같은 alert은 5분 내 재발송하지 않음

## 설정 (config.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # API Keys (optional)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    github_token: str | None = None
    zhipuai_api_key: str | None = None
    gemini_api_key: str | None = None

    # OpenClaw
    openclaw_gateway_url: str = "http://localhost:18789"
    openclaw_gateway_token: str | None = None

    # License
    license_key: str | None = None

    # Thresholds (JSON string → 파싱)
    alert_config_path: str = "config/alerts.json"

    class Config:
        env_file = ".env"
```
