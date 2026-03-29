# Tiny Monitor QA Test Plan

## 1. 경계면 검증 (Task #13)

API 응답 JSON shape과 프론트엔드 JS가 기대하는 shape을 교차 비교한다.

### 1.1 REST API 경계면

| 엔드포인트 | 백엔드 응답 shape | 프론트엔드 파싱 위치 | 검증 항목 |
|---|---|---|---|
| `GET /api/metrics` | `SystemSnapshot` (JSON) | `app.js` / `charts.js` | 필드명, 타입, null 가능 여부 |
| `GET /api/usage` | `UsageSnapshot` (JSON) | `app.js` | usages 배열 구조, cost_usd nullable |
| `GET /api/alerts` | `list[AlertEvent]` (JSON) | `app.js` | level enum 값, timestamp 형식 |
| `GET /api/config` | `{thresholds, providers}` | `settings.js` | threshold 필드명, 배열 구조 |
| `POST /api/config` | `{status: "updated"}` | `settings.js` | 성공/실패 응답 처리 |
| `GET /api/health` | `{status, uptime_seconds}` | `app.js` | 타입 일치 |

### 1.2 WebSocket 경계면

| 메시지 타입 | 서버 shape | 클라이언트 파싱 | 검증 항목 |
|---|---|---|---|
| `system_metrics` | `{type, data: SystemSnapshot}` | `websocket.js` → `charts.js` | data 내부 필드 매핑 |
| `usage_update` | `{type, data: UsageSnapshot}` | `websocket.js` → `app.js` | usages 배열 처리 |
| `alert` | `{type, data: AlertEvent}` | `websocket.js` → `app.js` | level별 UI 반영 |

### 1.3 Port-Adapter 경계면

| Port | 반환 타입 | 어댑터 | 검증 항목 |
|---|---|---|---|
| `MetricsPort.collect()` | `SystemSnapshot` | psutil, macmon | 모든 필드 채워지는지, Optional 필드 처리 |
| `UsagePort.fetch_usage()` | `list[TokenUsage]` | anthropic, openai, github, zhipuai, gemini | provider명, 토큰 카운트 타입 |
| `NotificationPort.send_alert()` | `bool` | openclaw_notifier | AlertEvent 직렬화 |

## 2. 통합 테스트 (Task #14)

pytest 기반으로 API/어댑터 통합 테스트를 작성한다.

### 2.1 테스트 구조
```
tests/
├── conftest.py              # 공통 fixture (TestClient, mock adapters)
├── test_api_health.py       # /api/health 엔드포인트
├── test_api_metrics.py      # /api/metrics 엔드포인트
├── test_api_usage.py        # /api/usage 엔드포인트
├── test_api_alerts.py       # /api/alerts 엔드포인트
├── test_api_config.py       # /api/config 엔드포인트
├── test_websocket.py        # WebSocket 연결 및 메시지
├── test_alert_service.py    # Threshold 감지 로직
└── test_adapters.py         # 어댑터 단위 테스트
```

### 2.2 테스트 시나리오

**API 테스트:**
- 각 엔드포인트 정상 응답 (200)
- 응답 JSON shape이 도메인 모델과 일치
- 에러 시나리오 (어댑터 실패 시 graceful 응답)

**WebSocket 테스트:**
- 연결 수립
- subscribe 메시지 처리
- system_metrics 브로드캐스트 수신

**어댑터 테스트:**
- psutil 어댑터: SystemSnapshot 반환 shape 검증
- AI 사용량 어댑터: mock HTTP로 TokenUsage 반환 검증
- 알림 어댑터: mock HTTP로 send_alert 호출 검증

## 3. Threshold 알림 테스트 (Task #15)

### 3.1 AlertService 단위 테스트
- CPU 80% 초과 → warning 이벤트 생성
- CPU 95% 초과 → critical 이벤트 생성
- 임계값 미만 → 이벤트 미생성
- token_cost 임계값 테스트

### 3.2 알림 E2E 흐름
- 메트릭 수집 → threshold 체크 → AlertEvent 생성 → WebSocket alert 브로드캐스트
- AlertEvent 생성 → OpenClaw 알림 발송 (mock)
- 프론트엔드 alert 메시지 수신 → UI 경고 표시

### 3.3 프론트엔드 알림 UI 검증 (수동)
- warning 레벨: 노란색 경고 표시
- critical 레벨: 빨간색 경고 표시
- 알림 목록에 추가

## 의존성 태스크 모니터링

| QA 태스크 | 선행 태스크 | 상태 |
|---|---|---|
| #13 경계면 검증 | #2 (FastAPI 서버), #5 (대시보드 HTML) | 대기 |
| #14 통합 테스트 | #3 (WebSocket), #9 (시스템 메트릭 어댑터), #10 (AI 사용량 어댑터) | 대기 |
| #15 Threshold 알림 | #14 (통합 테스트) | 대기 |
