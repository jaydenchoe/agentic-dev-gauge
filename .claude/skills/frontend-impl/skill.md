---
name: frontend-impl
description: "Tiny Monitor 프론트엔드 구현 가이드. 반응형 다크 테마 대시보드, 실시간 차트, threshold 경고 시각화, WebSocket 클라이언트 구현 방법을 안내한다. frontend-dev 에이전트가 참조하는 스킬."
---

# Frontend Implementation Guide

## 디렉토리 구조

```
src/static/
├── index.html          # 메인 대시보드
├── settings.html       # 설정 페이지
├── css/
│   └── style.css       # 전체 스타일 (다크 테마, 반응형)
├── js/
│   ├── app.js          # 메인 로직, 초기화
│   ├── websocket.js    # WebSocket 클라이언트
│   ├── charts.js       # 차트/시각화 (Canvas 기반)
│   └── settings.js     # 설정 UI 로직
└── assets/
    └── (아이콘 등 필요 시)
```

## 디자인 시스템

### 색상 팔레트 (CSS 변수)

```css
:root {
  /* 배경 */
  --bg-primary: #0a0a0f;
  --bg-card: #12121a;
  --bg-card-hover: #1a1a25;

  /* 텍스트 */
  --text-primary: #e4e4e7;
  --text-secondary: #71717a;
  --text-muted: #52525b;

  /* 상태 색상 */
  --color-normal: #22c55e;
  --color-warning: #f59e0b;
  --color-critical: #ef4444;
  --color-info: #3b82f6;

  /* 게이지/차트 */
  --gauge-bg: #27272a;
  --gauge-fill-normal: linear-gradient(135deg, #22c55e, #16a34a);
  --gauge-fill-warning: linear-gradient(135deg, #f59e0b, #d97706);
  --gauge-fill-critical: linear-gradient(135deg, #ef4444, #dc2626);

  /* 보더/구분선 */
  --border-color: #27272a;

  /* 그림자 */
  --shadow-card: 0 4px 6px -1px rgba(0,0,0,0.3);
}
```

### 반응형 브레이크포인트

```css
/* 1열: iPhone, 좁은 창 */
@media (max-width: 499px) {
  .dashboard-grid { grid-template-columns: 1fr; }
}

/* 2열: 하기비스(960x540), 중간 창 */
@media (min-width: 500px) and (max-width: 959px) {
  .dashboard-grid { grid-template-columns: 1fr 1fr; }
}

/* 3열: iPad, 풀스크린 */
@media (min-width: 960px) {
  .dashboard-grid { grid-template-columns: 1fr 1fr 1fr; }
}
```

## 대시보드 레이아웃

```
┌─────────────────────────────────────────────┐
│  Tiny Monitor          ⚙️ Settings  🔑 Pro  │  ← 헤더
├─────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│ │  CPU    │ │  RAM    │ │  Disk   │       │  ← 시스템 메트릭
│ │  ◔ 45%  │ │  ◔ 62%  │ │  ◔ 47%  │       │     (원형 게이지)
│ │ ▁▃▅▇▅▃▁ │ │ ▁▃▅▇▅▃▁ │ │ ▁▃▅▇▅▃▁ │       │     + 스파크라인
│ └─────────┘ └─────────┘ └─────────┘       │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│ │  GPU    │ │  NPU    │ │  Temp   │       │
│ │  ◔ 30%  │ │  2.5W   │ │  62°C   │       │
│ └─────────┘ └─────────┘ └─────────┘       │
├─────────────────────────────────────────────┤
│ ┌───────────────────────────────────────┐   │
│ │  AI Service Usage                     │   │  ← AI 사용량
│ │  Claude Opus   ████████░░ 80%  ⚠️    │   │     (수평 바)
│ │  Claude Sonnet ██████░░░░ 60%        │   │
│ │  OpenAI        ████░░░░░░ 40%        │   │
│ │  Copilot       ██████████ 95%  🔴    │   │
│ │  GLM           ██░░░░░░░░ 20%        │   │
│ │  Gemini        ███░░░░░░░ 30%        │   │
│ └───────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## 카드 컴포넌트

### 시스템 메트릭 카드
- 원형 게이지 (SVG circle + dasharray 애니메이션)
- 중앙에 수치 (%)
- 하단에 스파크라인 (최근 60초)
- threshold 초과 시: 게이지 색상 변경 + 카드 border 색상 변경

### AI 사용량 카드
- 수평 프로그레스 바
- 서비스명 + 사용량/한도 텍스트
- threshold 초과 시: 바 색상 변경 + 경고 아이콘
- 한도 없는 서비스(종량제): 비용($) 표시

### Threshold 경고 시각화
- **normal** (< warning): 초록색 게이지, 아이콘 없음
- **warning** (>= warning, < critical): 노란색 게이지 + ⚠️ 아이콘 + 카드 border 노란색
- **critical** (>= critical): 빨간색 게이지 + 🔴 아이콘 + 카드 border 빨간색 + 부드러운 pulse 애니메이션

```css
@keyframes pulse-warning {
  0%, 100% { border-color: var(--color-warning); }
  50% { border-color: transparent; }
}
.card--critical {
  animation: pulse-critical 2s ease-in-out infinite;
  border-color: var(--color-critical);
}
```

## WebSocket 클라이언트 (websocket.js)

```javascript
class MonitorWebSocket {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.listeners = { metrics: [], usage: [], alert: [] };
  }

  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      (this.listeners[msg.type] || []).forEach(fn => fn(msg.data));
    };
    this.ws.onclose = () => this._reconnect();
    this.ws.onerror = () => this.ws.close();
  }

  on(type, callback) {
    this.listeners[type]?.push(callback);
  }

  _reconnect() {
    setTimeout(() => {
      this.connect();
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
    }, this.reconnectDelay);
  }
}
```

## 차트 구현 (charts.js)

### 원형 게이지 (SVG)
- SVG `<circle>` 두 개: 배경 + 전경
- `stroke-dasharray`와 `stroke-dashoffset`로 퍼센트 표현
- CSS transition으로 부드러운 업데이트

### 스파크라인 (Canvas)
- Canvas 2D로 직접 그리기
- 최근 60개 데이터 포인트
- 선 색상: 현재 상태(normal/warning/critical)에 따라 변경
- 배경 그라데이션 fill

### 프로그레스 바 (CSS)
- `width` 퍼센트로 fill
- CSS transition으로 부드러운 업데이트
- 색상은 상태에 따라 CSS 변수 변경

## 설정 페이지 (settings.html)

- API 키 입력 (각 서비스별, password 타입)
- Threshold 설정 (각 메트릭별 warning/critical 슬라이더)
- OpenClaw Gateway URL/Token 입력
- 라이선스 키 입력 + 검증 버튼
- 저장 시 PUT /api/config 호출

## Pro/Free 티어 UI

```javascript
// Free: 모니터링만
// Pro: + 에이전틱 기능 표시
if (licenseData.tier === 'pro') {
  document.getElementById('agentic-panel').style.display = 'block';
}
```

Pro 전용 패널:
- 비용 예측 차트
- 자동 최적화 제안
- 일일 보고서 뷰
