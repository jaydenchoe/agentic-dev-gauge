---
name: tiny-monitor-orchestrator
description: "OpenClaw Tiny Monitor 프로젝트의 전체 빌드를 오케스트레이션한다. 시스템 모니터링 + AI 토큰 사용량 추적 웹앱을 Hexagonal Architecture로 구현. '빌드 시작', '구현 시작', 'tiny monitor 만들어', '하네스 실행' 요청 시 트리거."
---

# Tiny Monitor Orchestrator

OpenClaw Tiny Monitor의 전체 빌드를 조율하는 오케스트레이터. 4명의 에이전트 팀(backend-dev, frontend-dev, adapter-dev, qa-engineer)을 구성하여 Hexagonal Architecture 기반 웹앱을 구현한다.

## 실행 모드: 에이전트 팀

## 에이전트 구성

| 팀원 | 에이전트 타입 | 역할 | 스킬 | 출력 |
|------|-------------|------|------|------|
| backend-dev | backend-dev | FastAPI 서버, 서비스, 포트 정의 | backend-impl | `src/main.py`, `src/core/`, `src/services/`, `src/api/` |
| frontend-dev | frontend-dev | 반응형 웹 UI | frontend-impl | `src/static/` |
| adapter-dev | adapter-dev | 시스템/AI/알림 어댑터 | api-integration | `src/adapters/` |
| qa-engineer | qa-engineer | 통합 테스트 | — | `tests/`, `_workspace/qa_report.md` |

## 워크플로우

### Phase 1: 아키텍처 설계 (오케스트레이터가 직접 수행)

1. `_workspace/` 디렉토리 생성
2. 아키텍처 설계 문서 작성 → `_workspace/01_architecture.md`
   - 디렉토리 구조
   - Port(인터페이스) 목록
   - API 엔드포인트 스펙
   - WebSocket 메시지 포맷
   - 도메인 모델 정의
3. 프로젝트 초기 구조 생성:
   ```
   src/
   ├── main.py
   ├── config.py
   ├── core/
   │   ├── __init__.py
   │   ├── models.py        # 도메인 모델
   │   └── ports/
   │       ├── __init__.py
   │       ├── metrics.py    # MetricsPort ABC
   │       ├── usage.py      # UsagePort ABC
   │       └── notification.py # NotificationPort ABC
   ├── services/
   ├── api/
   ├── adapters/
   └── static/
   ```

### Phase 2: 팀 구성 및 병렬 개발

1. 팀 생성:
   ```
   TeamCreate(
     team_name: "tiny-monitor-team",
     members: [
       { name: "backend-dev", agent_type: "backend-dev", model: "opus",
         prompt: "아키텍처 설계 문서(_workspace/01_architecture.md)를 읽고 FastAPI 백엔드를 구현하라. Port 인터페이스를 먼저 정의하고 frontend-dev에게 API 스펙을, adapter-dev에게 Port 정의를 공유하라. Skill 도구로 /backend-impl을 호출하여 상세 가이드를 참조하라." },
       { name: "frontend-dev", agent_type: "frontend-dev", model: "opus",
         prompt: "아키텍처 설계 문서(_workspace/01_architecture.md)를 읽고 반응형 웹 UI를 구현하라. backend-dev로부터 API 스펙을 받은 뒤 구현을 시작하라. Skill 도구로 /frontend-impl을 호출하여 상세 가이드를 참조하라." },
       { name: "adapter-dev", agent_type: "adapter-dev", model: "opus",
         prompt: "아키텍처 설계 문서(_workspace/01_architecture.md)를 읽고 어댑터를 구현하라. backend-dev로부터 Port 정의를 받은 뒤 구현을 시작하라. Skill 도구로 /api-integration을 호출하여 상세 가이드를 참조하라." },
       { name: "qa-engineer", agent_type: "qa-engineer", model: "opus",
         prompt: "아키텍처 설계 문서(_workspace/01_architecture.md)를 읽고 테스트 계획을 수립하라. 각 팀원의 모듈이 완성될 때마다 점진적으로 검증하라. 경계면 교차 비교에 집중하라." }
     ]
   )
   ```

2. 작업 등록:
   ```
   TaskCreate(tasks: [
     { title: "Port 인터페이스 정의", assignee: "backend-dev", description: "core/ports/ 에 MetricsPort, UsagePort, NotificationPort ABC 정의" },
     { title: "FastAPI 서버 구현", assignee: "backend-dev", description: "main.py, api/ 라우터, services/ 서비스 레이어 구현", depends_on: ["Port 인터페이스 정의"] },
     { title: "WebSocket 엔드포인트", assignee: "backend-dev", description: "/ws/live 실시간 메트릭 스트리밍", depends_on: ["FastAPI 서버 구현"] },
     { title: "설정 관리", assignee: "backend-dev", description: "config.py, .env.example 생성", depends_on: ["Port 인터페이스 정의"] },
     { title: "대시보드 HTML/CSS", assignee: "frontend-dev", description: "반응형 레이아웃, 다크 테마, 카드 컴포넌트" },
     { title: "실시간 차트", assignee: "frontend-dev", description: "게이지, 바 차트, 스파크라인 구현", depends_on: ["대시보드 HTML/CSS"] },
     { title: "WebSocket 클라이언트", assignee: "frontend-dev", description: "실시간 데이터 수신 및 UI 업데이트", depends_on: ["대시보드 HTML/CSS"] },
     { title: "설정 UI", assignee: "frontend-dev", description: "API 키 입력, threshold 설정 화면", depends_on: ["대시보드 HTML/CSS"] },
     { title: "시스템 메트릭 어댑터", assignee: "adapter-dev", description: "PsutilAdapter, MacmonAdapter 구현", depends_on: ["Port 인터페이스 정의"] },
     { title: "AI 사용량 어댑터", assignee: "adapter-dev", description: "Anthropic, OpenAI, Copilot, ZhipuAI, Gemini 어댑터", depends_on: ["Port 인터페이스 정의"] },
     { title: "OpenClaw 연동 어댑터", assignee: "adapter-dev", description: "openclaw status --usage 파싱 + Gateway 알림", depends_on: ["Port 인터페이스 정의"] },
     { title: "알림 어댑터", assignee: "adapter-dev", description: "OpenClawNotifier 구현", depends_on: ["Port 인터페이스 정의"] },
     { title: "경계면 검증", assignee: "qa-engineer", description: "API 응답 shape vs 프론트엔드 기대 shape 교차 비교", depends_on: ["FastAPI 서버 구현", "대시보드 HTML/CSS"] },
     { title: "통합 테스트", assignee: "qa-engineer", description: "pytest 기반 API/어댑터 통합 테스트", depends_on: ["WebSocket 엔드포인트", "시스템 메트릭 어댑터", "AI 사용량 어댑터"] },
     { title: "Threshold 알림 테스트", assignee: "qa-engineer", description: "임계값 초과 시 UI 경고 + OpenClaw 알림 동작 검증", depends_on: ["통합 테스트"] }
   ])
   ```

**팀원 간 통신 규칙:**
- backend-dev는 Port 정의 완료 즉시 adapter-dev와 frontend-dev에게 SendMessage
- adapter-dev는 각 어댑터 완료 시 backend-dev에게 SendMessage
- frontend-dev는 API 연동 완료 시 qa-engineer에게 SendMessage
- qa-engineer는 버그 발견 시 해당 팀원에게 직접 SendMessage

**산출물 저장:**

| 팀원 | 출력 경로 |
|------|----------|
| backend-dev | `src/main.py`, `src/core/`, `src/services/`, `src/api/`, `src/config.py` |
| frontend-dev | `src/static/index.html`, `src/static/css/`, `src/static/js/` |
| adapter-dev | `src/adapters/system/`, `src/adapters/ai_usage/`, `src/adapters/notification/` |
| qa-engineer | `tests/`, `_workspace/qa_report.md` |

### Phase 3: 통합 및 최종 검증

1. 모든 팀원의 작업 완료 대기 (TaskGet으로 상태 확인)
2. qa-engineer의 보고서 확인
3. 버그가 있으면 해당 팀원에게 수정 요청 (SendMessage)
4. 최종 파일 생성:
   - `requirements.txt`
   - `.env.example`
   - `README.md` (실행 방법)
   - `run.sh` (실행 스크립트)

### Phase 4: 정리

1. 팀원들에게 종료 요청 (SendMessage)
2. 팀 정리 (TeamDelete)
3. `_workspace/` 보존
4. 사용자에게 결과 요약 보고

## 데이터 흐름

```
[오케스트레이터]
    │ Phase 1: 아키텍처 설계 → _workspace/01_architecture.md
    │
    ▼ Phase 2: TeamCreate
[backend-dev] ←SendMessage→ [frontend-dev]
      │                           │
      │ Port 정의                  │ API 스펙 수신
      ▼                           ▼
[adapter-dev] ──────────→ [qa-engineer]
      │                       │
      ▼                       ▼
  src/adapters/          tests/ + qa_report.md
      │                       │
      └───────── Read ────────┘
                  ↓
          [오케스트레이터: 통합]
                  ↓
           최종 프로젝트
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 팀원 1명 실패 | 리더가 SendMessage로 상태 확인 → 재시작 또는 작업 재할당 |
| Port↔Adapter 불일치 | qa-engineer가 감지 → 양측에 SendMessage → 수정 |
| API 스펙 변경 | backend-dev가 변경 사항 브로드캐스트 → frontend-dev/adapter-dev 반영 |
| 외부 API 접근 불가 | adapter-dev가 Mock 데이터로 대체, 보고서에 명시 |
| 타임아웃 | 현재까지 완성된 코드 보존, 미완료 부분 보고 |

## 테스트 시나리오

### 정상 흐름
1. 오케스트레이터가 아키텍처 설계 완료
2. 4명 팀원이 병렬 개발 시작
3. backend-dev가 Port 정의 → adapter-dev, frontend-dev에 공유
4. 각 팀원이 모듈 완성 → qa-engineer가 점진적 검증
5. 통합 테스트 통과
6. 최종 프로젝트 생성 (서버 기동 가능)

### 에러 흐름
1. adapter-dev가 Anthropic API 어댑터에서 인증 에러 발생
2. Mock 데이터로 대체하여 나머지 작업 계속
3. qa-engineer가 경계면 검증 중 WebSocket 메시지 형식 불일치 발견
4. backend-dev에게 SendMessage → 수정 → 재검증
5. 최종 보고서에 "Anthropic 어댑터 실제 API 검증 미완료" 명시
