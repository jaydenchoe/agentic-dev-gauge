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

## 행동 규칙
- **PR 머지 전 반드시 확인**: 스크린샷 또는 API 테스트로 변경사항이 정상 동작하는지 확인한 후 머지. 확인 안 된 PR은 머지 금지.
- **대시보드 수치를 신뢰**: 사용자가 대시보드 값을 질문하면, 다른 CLI 도구(df, free 등)의 출력으로 대시보드를 부정하지 말 것. 먼저 우리 코드의 계산 방식을 설명할 것.
- **run_in_background 완료 알림 무시**: 서버를 background로 시작했을 때 task 완료 알림이 와도 서버가 종료된 것이 아님. 불필요한 재시작/로그 확인 금지.
- **디버그 Chrome은 pkill 금지**: 기존 Chrome과 별도 인스턴스로 실행. 절대 pkill로 Chrome 프로세스를 죽이지 말 것.
