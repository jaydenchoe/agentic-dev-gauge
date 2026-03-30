# OpenClaw Tiny Monitor

시스템 리소스(CPU, 메모리, 디스크, 네트워크, GPU)와 AI 토큰 사용량(Anthropic, OpenAI, GitHub Copilot, ZhipuAI, Gemini)을 실시간 모니터링하는 웹 대시보드.

## Quick Start

```bash
# 실행
./run.sh

# 또는 수동 실행
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/main.py
```

브라우저에서 `http://localhost:8080` 접속.

## 설정

`.env.example`을 `.env`로 복사하여 설정:

```bash
cp .env.example .env
```

주요 설정:
- `PORT` — 서버 포트 (기본: 8080)
- `METRICS_INTERVAL_SEC` — 시스템 메트릭 수집 주기 (기본: 2초)
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` 등 — AI 사용량 조회용 API 키
- `OPENCLAW_GATEWAY_URL` — OpenClaw Gateway 알림 URL

API 키는 대시보드 설정 화면에서도 입력 가능.

## 아키텍처

Hexagonal Architecture (포트/어댑터 패턴):

```
src/
├── core/          # 도메인 모델 + Port 인터페이스 (외부 의존성 없음)
├── services/      # 비즈니스 로직 (Port를 통해 어댑터 사용)
├── api/           # FastAPI REST + WebSocket 엔드포인트
├── adapters/      # Port 구현체 (psutil, httpx, subprocess)
└── static/        # 프론트엔드 (vanilla HTML/CSS/JS + Chart.js)
```

## 테스트

```bash
.venv/bin/python -m pytest tests/ -v
```

## 기술 스택

- **Backend:** Python 3.11+, FastAPI, uvicorn, pydantic-settings
- **System Metrics:** psutil (cross-platform), macmon (Apple Silicon)
- **Frontend:** Vanilla HTML/CSS/JS, Chart.js (CDN)
- **AI Usage APIs:** httpx (async HTTP)
