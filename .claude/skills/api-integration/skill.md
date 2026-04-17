---
name: api-integration
description: "Tiny Monitor API 어댑터 구현 가이드. psutil/macmon 시스템 메트릭 수집, Anthropic/OpenAI/GitHub/ZhipuAI/Gemini 사용량 API 연동, OpenClaw Gateway 알림 발송, GeekMagic SmallTV Ultra 외부 디스플레이 푸시 방법을 안내한다. adapter-dev 에이전트가 참조하는 스킬."
---

# API Integration Guide

## 어댑터 디렉토리 구조

```
src/adapters/
├── __init__.py
├── system/
│   ├── __init__.py
│   ├── psutil_adapter.py     # CPU, RAM, Disk
│   └── macmon_adapter.py     # GPU, NPU, Temperature
├── ai_usage/
│   ├── __init__.py
│   ├── anthropic_adapter.py  # Claude Opus/Sonnet
│   ├── openai_adapter.py     # GPT/Codex
│   ├── copilot_adapter.py    # GitHub Copilot
│   ├── zhipuai_adapter.py    # GLM
│   ├── gemini_adapter.py     # Google Gemini
│   └── openclaw_usage_adapter.py  # openclaw status --usage 파싱
├── notification/
│   ├── __init__.py
│   └── openclaw_notifier.py  # Gateway POST 알림
├── display/
│   ├── __init__.py
│   └── geekmagic_adapter.py  # SmallTV Ultra 240x240 PNG 푸시
└── license/
    ├── __init__.py
    └── lemonsqueezy_adapter.py  # 라이선스 검증
```

## 시스템 메트릭 어댑터

### PsutilAdapter

```python
import psutil
from core.ports.metrics import MetricsPort
from core.models import SystemMetrics

class PsutilAdapter(MetricsPort):
    async def get_system_metrics(self) -> SystemMetrics:
        cpu = psutil.cpu_percent(interval=None)  # non-blocking
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return SystemMetrics(
            cpu_percent=cpu,
            ram_used_gb=ram.used / (1024**3),
            ram_total_gb=ram.total / (1024**3),
            disk_used_gb=disk.used / (1024**3),
            disk_total_gb=disk.total / (1024**3),
        )
```

구현 주의:
- `cpu_percent(interval=None)`: 이전 호출 이후의 평균. 첫 호출은 0.0 반환하므로 초기화 시 한 번 호출
- psutil은 동기 라이브러리. `asyncio.to_thread()`로 감싸서 이벤트 루프 블로킹 방지

### MacmonAdapter

macmon은 CLI 도구로 JSON 출력을 지원한다. subprocess로 호출하여 파싱.

```python
import asyncio
import json
from core.models import SystemMetrics

class MacmonAdapter:
    """GPU, NPU, Temperature 메트릭 (macmon CLI 의존)"""

    async def get_gpu_metrics(self) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                'macmon', 'read', '--json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            data = json.loads(stdout)
            return {
                'gpu_percent': data.get('gpu_usage', {}).get('percent'),
                'npu_power_w': data.get('ane_power'),
                'temperature_c': data.get('cpu_temp_avg'),
            }
        except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
            return {'gpu_percent': None, 'npu_power_w': None, 'temperature_c': None}
```

구현 주의:
- macmon 미설치 시 FileNotFoundError → None 반환, 에러 없이 graceful degradation
- macmon은 macOS Apple Silicon 전용. Linux에서는 항상 None 반환
- macmon 출력 포맷은 버전에 따라 다를 수 있음. 실제 JSON 키를 확인하여 조정 필요

## AI 사용량 어댑터

### AnthropicUsageAdapter

```python
import httpx
from datetime import datetime, timedelta
from core.ports.usage import UsagePort
from core.models import AIServiceUsage

class AnthropicUsageAdapter(UsagePort):
    BASE_URL = "https://api.anthropic.com/v1/organizations"

    def __init__(self, api_key: str, model_filter: str = "claude-opus"):
        self.api_key = api_key
        self.model_filter = model_filter  # "claude-opus" or "claude-sonnet"
        self._service = f"claude_{model_filter.split('-')[-1]}"

    def service_name(self) -> str:
        return self._service

    async def get_usage(self) -> AIServiceUsage:
        now = datetime.utcnow()
        start = now.replace(day=1, hour=0, minute=0, second=0)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/usage_report/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                params={
                    "start_time": start.isoformat() + "Z",
                    "end_time": now.isoformat() + "Z",
                    "group_by": "model",
                    "time_bucket": "1d",
                }
            )
            resp.raise_for_status()
            data = resp.json()
            total_tokens = self._sum_tokens(data, self.model_filter)
            return AIServiceUsage(
                service_name=self._service,
                used_tokens=total_tokens,
                limit_tokens=None,
                used_cost_usd=self._estimate_cost(total_tokens),
                limit_cost_usd=None,
                period="monthly",
            )

    def _sum_tokens(self, data: dict, model_filter: str) -> int:
        # Usage report의 buckets에서 해당 모델의 토큰 합산
        total = 0
        for bucket in data.get("data", []):
            if model_filter in bucket.get("model", ""):
                total += bucket.get("output_tokens", 0) + bucket.get("input_tokens", 0)
        return total

    def _estimate_cost(self, tokens: int) -> float:
        # 대략적 비용 추정 (Opus: $30/1M tokens avg)
        if "opus" in self._service:
            return tokens * 15 / 1_000_000  # avg of input($5) + output($25)
        return tokens * 9 / 1_000_000  # Sonnet avg
```

### OpenAIUsageAdapter

```python
class OpenAIUsageAdapter(UsagePort):
    BASE_URL = "https://api.openai.com/v1/organization/usage"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def service_name(self) -> str:
        return "openai"

    async def get_usage(self) -> AIServiceUsage:
        now = datetime.utcnow()
        start = int((now - timedelta(days=30)).timestamp())
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={"start_time": start}
            )
            resp.raise_for_status()
            data = resp.json()
            total_tokens = sum(
                b.get("result", {}).get("input_tokens", 0) +
                b.get("result", {}).get("output_tokens", 0)
                for b in data.get("data", [])
            )
            return AIServiceUsage(
                service_name="openai",
                used_tokens=total_tokens,
                limit_tokens=None,
                used_cost_usd=None,
                limit_cost_usd=None,
                period="monthly",
            )
```

### CopilotUsageAdapter

GitHub REST API로 조직 단위 메트릭 조회. 개인 사용자는 제한적.

```python
class CopilotUsageAdapter(UsagePort):
    def __init__(self, github_token: str, org: str | None = None):
        self.token = github_token
        self.org = org

    def service_name(self) -> str:
        return "copilot"

    async def get_usage(self) -> AIServiceUsage:
        if not self.org:
            # 개인 사용자: premium requests 조회 시도
            return AIServiceUsage(
                service_name="copilot",
                used_tokens=0,
                limit_tokens=None,
                used_cost_usd=None,
                limit_cost_usd=None,
                period="monthly",
            )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/orgs/{self.org}/copilot/usage",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json"
                }
            )
            resp.raise_for_status()
            data = resp.json()
            # 조직 사용량 집계
            total = sum(d.get("total_completions", 0) for d in data)
            return AIServiceUsage(
                service_name="copilot",
                used_tokens=total,
                limit_tokens=None,
                used_cost_usd=None,
                limit_cost_usd=None,
                period="monthly",
            )
```

### ZhipuAIUsageAdapter

```python
class ZhipuAIUsageAdapter(UsagePort):
    BASE_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def service_name(self) -> str:
        return "glm"

    async def get_usage(self) -> AIServiceUsage:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.BASE_URL,
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            resp.raise_for_status()
            data = resp.json()
            return AIServiceUsage(
                service_name="glm",
                used_tokens=data.get("used", 0),
                limit_tokens=data.get("limit", None),
                used_cost_usd=None,
                limit_cost_usd=None,
                period="monthly",
            )
```

### GeminiUsageAdapter

Gemini는 공식 사용량 API가 없으므로, 자체 토큰 카운팅 방식 사용.

```python
class GeminiUsageAdapter(UsagePort):
    """자체 토큰 카운팅 방식. 앱 내에서 누적 관리."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._accumulated_tokens = 0

    def service_name(self) -> str:
        return "gemini"

    def add_tokens(self, input_tokens: int, output_tokens: int):
        """외부에서 Gemini API 호출 후 토큰 누적"""
        self._accumulated_tokens += input_tokens + output_tokens

    async def get_usage(self) -> AIServiceUsage:
        return AIServiceUsage(
            service_name="gemini",
            used_tokens=self._accumulated_tokens,
            limit_tokens=None,
            used_cost_usd=None,
            limit_cost_usd=None,
            period="session",
        )
```

### OpenClawUsageAdapter

`openclaw status --usage --json` 출력을 파싱하여 모든 AI 서비스 사용량을 한번에 조회.

```python
class OpenClawUsageAdapter:
    """openclaw CLI를 통한 통합 사용량 조회"""

    async def get_all_usage(self) -> list[AIServiceUsage]:
        try:
            proc = await asyncio.create_subprocess_exec(
                'openclaw', 'status', '--usage', '--json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            data = json.loads(stdout)
            return [self._parse_service(s) for s in data.get("services", [])]
        except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
            return []

    def _parse_service(self, service: dict) -> AIServiceUsage:
        return AIServiceUsage(
            service_name=service.get("name", "unknown"),
            used_tokens=service.get("used_tokens", 0),
            limit_tokens=service.get("limit_tokens"),
            used_cost_usd=service.get("used_cost_usd"),
            limit_cost_usd=service.get("limit_cost_usd"),
            period=service.get("period", "monthly"),
        )
```

## 알림 어댑터

### OpenClawNotifier

```python
class OpenClawNotifier(NotificationPort):
    def __init__(self, gateway_url: str, token: str | None = None):
        self.gateway_url = gateway_url.rstrip('/')
        self.token = token

    async def send_alert(self, alert: Alert) -> bool:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        message = f"[Tiny Monitor Alert] {alert.status.value.upper()}: {alert.message}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.gateway_url}/api/sessions/main/messages",
                    headers=headers,
                    json={"message": message},
                    timeout=5.0
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
```

## 라이선스 어댑터

### LemonSqueezyAdapter

```python
class LemonSqueezyAdapter:
    VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"

    async def verify(self, license_key: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.VALIDATE_URL,
                json={"license_key": license_key}
            )
            data = resp.json()
            return {
                "valid": data.get("valid", False),
                "tier": "pro" if data.get("valid") else "free",
            }
```

## 외부 디스플레이 어댑터 (GeekMagic SmallTV Ultra)

### 장치 프로토콜
- 엔드포인트 베이스: `http://{ULTRA_IP}` (ESP8266, 포트 80)
- 이미지 업로드: `POST /doUpload?dir=/image/` (multipart/form-data, 필드명 `file`, PNG 240x240, Content-Type `image/png`)
- 이미지 전환: `GET /set?img=/image/{filename}` (업로드 후 현재 화면에 반영)
- 테마 설정 (최초 1회): `GET /set?theme=3` (Ultra 기종은 theme=3)
- 펌웨어 버그: 업로드 응답에서 400 "Duplicate Content-Length" / "Data after" 문자열이 나올 수 있음 → 로깅만 하고 무시(정상 업로드로 취급)

### 구현 패턴
```python
import httpx
from src.core.ports.display import DisplayPort

class GeekMagicDisplayAdapter(DisplayPort):
    UPLOAD_FILENAME = "tm.png"  # 고정 파일명으로 덮어쓰기

    def __init__(self, base_url: str, timeout_sec: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_sec
        self._theme_set = False

    async def push_png(self, png_bytes: bytes) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if not self._theme_set:
                try:
                    await client.get(f"{self._base_url}/set?theme=3")
                    self._theme_set = True
                except httpx.HTTPError:
                    pass  # 다음 주기에 재시도
            files = {"file": (self.UPLOAD_FILENAME, png_bytes, "image/png")}
            try:
                r = await client.post(f"{self._base_url}/doUpload?dir=/image/", files=files)
            except httpx.HTTPError as exc:
                # 펌웨어가 malformed 응답을 내면 httpx가 RemoteProtocolError를 던지기도 함 → 업로드 자체는 성공일 수 있으므로 set 호출은 시도
                logger.debug("upload malformed: %s (continuing)", exc)
            try:
                await client.get(f"{self._base_url}/set?img=/image/{self.UPLOAD_FILENAME}")
            except httpx.HTTPError:
                return False
        return True
```

### 페이지 렌더러 (Pillow)
- 4페이지 카루셀: SYSTEM / CLAUDE / OTHER / LOCAL_LLM
- 페이지 전환: 5초마다 인덱스 회전 (`page = tick % 4`)
- 공통 템플릿: 상단바(타이틀 + 인디케이터) + 항목 3개 (라벨 / 퍼센트 / 프로그레스 바)
- 색상 팔레트: 배경 #0A0A0A, 정상 #10B981, 주의 #F59E0B, 경고 #F97316, 위험 #EF4444
- 폰트: 번들된 기본 sans (영문 전용). 항목 라벨 20px, 퍼센트 36~40px bold, 타이틀 18px
- 출력: `PIL.Image.save(buf, format="PNG")` → bytes

### 데이터 소스
- `app.state.monitor_service.latest` → `SystemSnapshot` (CPU/MEM/DISK %)
- `app.state.usage_service.claude_web_latest` → `ClaudeWebUsage` (session/weekly/sonnet %)
- `app.state.usage_service.latest.usages` → Codex/ZhipuAI 등 `TokenUsage` 리스트 (`quota_percentage` 사용)
- `app.state.usage_service.copilot_api_latest.quotas` → `premium_interactions` quota의 `percent_used`
- `app.state.usage_service.ollama_latest` → `OllamaUsage` (model, vram_percent, tok_per_sec)

### 라이프사이클 통합
- `src/main.py`의 lifespan에서 `GEEKMAGIC_ULTRA_IP` 설정이 있을 때만 adapter + 루프 task 생성
- `asyncio.create_task(pusher.run_forever(app.state))`
- shutdown 시 task cancel

## 공통 구현 원칙

1. **모든 어댑터는 Port ABC를 구현**: `core/ports/`에 정의된 인터페이스를 따름
2. **외부 형식 → 도메인 모델 변환**: API 응답의 raw 데이터를 `core/models.py`의 dataclass로 변환
3. **httpx AsyncClient 사용**: 비동기 HTTP 클라이언트
4. **Graceful degradation**: API 키 미설정/서비스 불가 시 에러 없이 빈/기본 데이터 반환
5. **캐싱**: 각 어댑터에 `_last_result`와 `_last_updated`를 두어, API 실패 시 이전 값 반환
