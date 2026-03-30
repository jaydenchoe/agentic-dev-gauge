# CLAUDE.md — OpenClaw Tiny Monitor

## 프로젝트 개요
시스템 리소스(CPU, RAM, Disk, GPU)와 AI 토큰 사용량(Anthropic, OpenAI, GitHub Copilot, ZhipuAI, Gemini)을 실시간 모니터링하는 웹 대시보드. Hexagonal Architecture(Ports & Adapters) 기반.

## 기술 스택
- Backend: Python 3.14, FastAPI, uvicorn, pydantic-settings
- Frontend: Vanilla JS + CSS (프레임워크 없음)
- 시스템 메트릭: psutil, macmon (Apple Silicon)
- 실시간 통신: WebSocket
- 외부 API: httpx (비동기)

## 디렉토리 구조
```
src/
  core/          # 도메인 모델, Port(ABC) 인터페이스
  services/      # 서비스 레이어 (MonitorService, UsageService, AlertService)
  adapters/      # Port 구현체 (system/, ai_usage/, notification/)
  api/           # REST routes, WebSocket 엔드포인트
  static/        # 프론트엔드 (HTML, CSS, JS)
tests/           # pytest 테스트
_workspace/      # 아키텍처 문서, QA 보고서
```

## 워크플로우 규칙
- **Task 단위 PR**: task 시작 시 feature 브랜치 생성 → 작업 + commit → task 완료 시 PR 생성 → main 머지
- 여러 task를 하나의 PR에 묶지 않는다
- main 브랜치는 항상 깨끗하게 유지

## 코딩 컨벤션
- 모든 어댑터는 Core의 Port(ABC) 인터페이스를 구현
- 외부 API 호출은 비동기 (httpx)
- API 키는 `.env`로 관리, 코드에 하드코딩 금지
- Core 도메인은 외부 의존성을 모름 (Hexagonal 원칙)
