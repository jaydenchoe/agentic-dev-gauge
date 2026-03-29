# Tiny Monitor Architecture

## Overview

OpenClaw Tiny Monitor는 시스템 리소스(CPU, 메모리, 디스크, 네트워크)와 AI 토큰 사용량(Anthropic, OpenAI, GitHub Copilot, ZhipuAI, Gemini)을 실시간 모니터링하는 웹 대시보드다. Hexagonal Architecture(포트/어댑터 패턴)로 구현한다.

## 디렉토리 구조

```
src/
├── main.py                  # FastAPI 앱 진입점
├── config.py                # 설정 관리 (pydantic-settings)
├── core/
│   ├── __init__.py
│   ├── models.py            # 도메인 모델 (dataclass)
│   └── ports/
│       ├── __init__.py
│       ├── metrics.py       # MetricsPort ABC
│       ├── usage.py         # UsagePort ABC
│       └── notification.py  # NotificationPort ABC
├── services/
│   ├── __init__.py
│   ├── monitor_service.py   # 메트릭 수집 오케스트레이션
│   ├── usage_service.py     # AI 사용량 수집 오케스트레이션
│   └── alert_service.py     # Threshold 감지 + 알림 발송
├── api/
│   ├── __init__.py
│   ├── routes.py            # REST 엔드포인트
│   └── websocket.py         # WebSocket 엔드포인트
├── adapters/
│   ├── __init__.py
│   ├── system/
│   │   ├── __init__.py
│   │   ├── psutil_adapter.py   # PsutilMetricsAdapter (Linux/Mac/Win)
│   │   └── macmon_adapter.py   # MacmonMetricsAdapter (macOS 전용, Apple Silicon)
│   ├── ai_usage/
│   │   ├── __init__.py
│   │   ├── anthropic_adapter.py
│   │   ├── openai_adapter.py
│   │   ├── github_adapter.py    # Copilot 사용량
│   │   ├── zhipuai_adapter.py
│   │   └── gemini_adapter.py
│   └── notification/
│       ├── __init__.py
│       └── openclaw_notifier.py  # OpenClaw Gateway 알림
└── static/
    ├── index.html
    ├── css/
    │   └── style.css
    └── js/
        ├── app.js            # 메인 앱 로직
        ├── charts.js         # 차트 렌더링
        ├── websocket.js      # WebSocket 클라이언트
        └── settings.js       # 설정 UI 로직
```

## 도메인 모델 (core/models.py)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class CpuMetrics:
    usage_percent: float          # 0-100
    per_core: list[float]         # 코어별 사용률
    frequency_mhz: Optional[float] = None
    temperature_celsius: Optional[float] = None  # macmon에서 제공

@dataclass
class MemoryMetrics:
    total_gb: float
    used_gb: float
    available_gb: float
    usage_percent: float          # 0-100

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
    """Apple Silicon GPU (macmon 전용)"""
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
    gpu: Optional[GpuMetrics] = None  # macmon이 있을 때만

@dataclass
class TokenUsage:
    provider: str                 # "anthropic", "openai", "github", "zhipuai", "gemini"
    model: str                    # 모델명
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Optional[float] = None
    period: str = "current_month" # 조회 기간

@dataclass
class UsageSnapshot:
    timestamp: datetime
    usages: list[TokenUsage]
    total_cost_usd: Optional[float] = None

@dataclass
class ThresholdConfig:
    metric: str                   # "cpu_percent", "memory_percent", "disk_percent", "token_cost"
    warning: float                # 경고 임계값
    critical: float               # 위험 임계값

@dataclass
class AlertEvent:
    timestamp: datetime
    metric: str
    current_value: float
    threshold: float
    level: str                    # "warning" | "critical"
    message: str
```

## Port 인터페이스 (core/ports/)

### MetricsPort (metrics.py)

```python
from abc import ABC, abstractmethod
from core.models import SystemSnapshot

class MetricsPort(ABC):
    @abstractmethod
    async def collect(self) -> SystemSnapshot:
        """시스템 메트릭을 수집하여 SystemSnapshot을 반환한다."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """이 어댑터가 현재 환경에서 사용 가능한지 반환한다."""
        ...
```

### UsagePort (usage.py)

```python
from abc import ABC, abstractmethod
from core.models import TokenUsage

class UsagePort(ABC):
    @abstractmethod
    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        """API 키를 사용하여 토큰 사용량을 조회한다."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다 (예: 'anthropic')."""
        ...
```

### NotificationPort (notification.py)

```python
from abc import ABC, abstractmethod
from core.models import AlertEvent

class NotificationPort(ABC):
    @abstractmethod
    async def send_alert(self, event: AlertEvent) -> bool:
        """알림을 발송하고 성공 여부를 반환한다."""
        ...
```

## API 엔드포인트 스펙

### REST API

| Method | Path | 설명 | Response |
|--------|------|------|----------|
| GET | `/api/health` | 헬스체크 | `{"status": "ok", "uptime_seconds": float}` |
| GET | `/api/metrics` | 현재 시스템 메트릭 | `SystemSnapshot` (JSON) |
| GET | `/api/usage` | AI 토큰 사용량 | `UsageSnapshot` (JSON) |
| GET | `/api/alerts` | 최근 알림 목록 | `list[AlertEvent]` (JSON) |
| GET | `/api/config` | 현재 설정 조회 | `{"thresholds": [...], "providers": [...]}` |
| POST | `/api/config` | 설정 업데이트 | `{"status": "updated"}` |
| GET | `/` | 대시보드 HTML | `index.html` (Static) |

### WebSocket

**Endpoint:** `ws://host:port/ws/live`

**서버 → 클라이언트 메시지:**

```json
{
  "type": "system_metrics",
  "data": {
    "timestamp": "2026-03-29T10:00:00Z",
    "cpu": {"usage_percent": 45.2, "per_core": [40.1, 50.3], "temperature_celsius": 55.0},
    "memory": {"total_gb": 16.0, "used_gb": 10.5, "available_gb": 5.5, "usage_percent": 65.6},
    "disk": {"total_gb": 500, "used_gb": 250, "free_gb": 250, "usage_percent": 50.0, "read_bytes_per_sec": 1024, "write_bytes_per_sec": 512},
    "network": {"bytes_sent_per_sec": 2048, "bytes_recv_per_sec": 4096},
    "gpu": {"usage_percent": 30.0, "memory_used_mb": 2048, "memory_total_mb": 8192}
  }
}
```

```json
{
  "type": "usage_update",
  "data": {
    "timestamp": "2026-03-29T10:00:00Z",
    "usages": [
      {"provider": "anthropic", "model": "claude-sonnet-4-6", "input_tokens": 50000, "output_tokens": 10000, "total_tokens": 60000, "cost_usd": 0.54}
    ],
    "total_cost_usd": 1.23
  }
}
```

```json
{
  "type": "alert",
  "data": {
    "timestamp": "2026-03-29T10:00:00Z",
    "metric": "cpu_percent",
    "current_value": 92.5,
    "threshold": 90.0,
    "level": "critical",
    "message": "CPU 사용률이 92.5%로 위험 임계값(90%)을 초과했습니다."
  }
}
```

**클라이언트 → 서버 메시지:**

```json
{
  "type": "subscribe",
  "channels": ["system_metrics", "usage_update", "alert"]
}
```

**메트릭 수집 주기:**
- 시스템 메트릭: 2초 간격
- AI 사용량: 60초 간격
- Threshold 체크: 매 메트릭 수집 시

## 설정 구조 (.env)

```env
# Server
HOST=0.0.0.0
PORT=8080

# System Metrics
METRICS_INTERVAL_SEC=2
METRICS_BACKEND=auto  # auto | psutil | macmon

# AI Usage API Keys (optional)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GITHUB_TOKEN=
ZHIPUAI_API_KEY=
GEMINI_API_KEY=

# Usage polling
USAGE_INTERVAL_SEC=60

# Thresholds (JSON string)
THRESHOLDS='[
  {"metric":"cpu_percent","warning":80,"critical":95},
  {"metric":"memory_percent","warning":80,"critical":95},
  {"metric":"disk_percent","warning":85,"critical":95},
  {"metric":"token_cost","warning":10.0,"critical":50.0}
]'

# OpenClaw Gateway (optional)
OPENCLAW_GATEWAY_URL=
OPENCLAW_API_KEY=
```

## 기술 스택

- **Backend:** Python 3.11+, FastAPI, uvicorn, pydantic, pydantic-settings
- **System Metrics:** psutil (cross-platform), macmon (macOS Apple Silicon)
- **Frontend:** Vanilla HTML/CSS/JS (no build step), Chart.js (CDN)
- **WebSocket:** FastAPI built-in WebSocket support
- **AI Usage APIs:** httpx (async HTTP client)

## 설계 원칙

1. **포트/어댑터 분리**: core는 외부 의존성 없음, 어댑터는 교체 가능
2. **점진적 기능**: API 키 없으면 해당 프로바이더 스킵 (에러 아님)
3. **단일 파일 배포 가능**: `python src/main.py`로 실행
4. **No build step**: 프론트엔드는 CDN + vanilla JS
5. **Graceful degradation**: macmon 없으면 psutil fallback, GPU 메트릭 생략
