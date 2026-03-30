# Tiny Monitor QA Report

## Test Summary

| Category | Tests | Passed | Failed |
|---|---|---|---|
| Adapter tests | 7 | 7 | 0 |
| Alert service tests | 12 | 12 | 0 |
| API integration tests | 14 | 14 | 0 |
| API shape / boundary tests | 8 | 8 | 0 |
| Service tests | 7 | 7 | 0 |
| WebSocket tests | 14 | 14 | 0 |
| **Total** | **63** | **63** | **0** |

## Boundary Verification Results (Task #13)

### REST API Boundaries

| Endpoint | Backend Shape | Frontend Parsing | Status |
|---|---|---|---|
| `GET /api/metrics` | `SystemSnapshot` dict | `app.js:handleSystemMetrics` | PASS |
| `GET /api/usage` | `UsageSnapshot` dict | `app.js:handleUsageUpdate` | PASS |
| `GET /api/alerts` | `list[AlertEvent]` | `app.js:handleAlert` | PASS |
| `GET /api/config` | `{thresholds[], providers[], gateway_url, gateway_configured}` | `settings.js:loadConfig` | PASS (fixed) |
| `POST /api/config` | handles thresholds + API keys + gateway | `settings.js:save` | PASS (fixed) |
| `GET /api/health` | `{status, uptime_seconds}` | `app.js:fetchInitialData` | PASS |

### WebSocket Boundaries

| Message Type | Server Shape | Client Parsing | Status |
|---|---|---|---|
| `system_metrics` | `{type, data: SystemSnapshot}` | `websocket.js` → `app.js` | PASS |
| `usage_update` | `{type, data: UsageSnapshot}` | `websocket.js` → `app.js` | PASS |
| `alert` | `{type, data: AlertEvent}` | `websocket.js` → `app.js` | PASS |
| `subscribe` (client→server) | `{type, channels[]}` | `websocket.py:80` | PASS |

### Port-Adapter Boundaries

| Port | Adapter | Returns Correct Type | Status |
|---|---|---|---|
| `MetricsPort.collect()` | PsutilMetricsAdapter | `SystemSnapshot` | PASS |
| `MetricsPort.collect()` | MacmonMetricsAdapter | `SystemSnapshot` | PASS (code review) |
| `UsagePort.fetch_usage()` | AnthropicUsageAdapter | `list[TokenUsage]` | PASS |
| `UsagePort.fetch_usage()` | OpenAIUsageAdapter | `list[TokenUsage]` | PASS |
| `UsagePort.fetch_usage()` | CopilotUsageAdapter | `list[TokenUsage]` | PASS (code review) |
| `UsagePort.fetch_usage()` | ZhipuAIUsageAdapter | `list[TokenUsage]` | PASS (code review) |
| `UsagePort.fetch_usage()` | GeminiUsageAdapter | `list[TokenUsage]` | PASS (code review) |
| `NotificationPort.send_alert()` | OpenClawNotifier | `bool` | PASS |

## Bugs Found & Fixed

### BUG-1: settings.js providers shape mismatch (CRITICAL) — FIXED

**Location:** `src/static/js/settings.js:50-58`
**Description:** Backend returned `providers` as array `[{name, configured}]`, but frontend accessed it as object with `_api_key` suffixed keys.
**Fix:** Frontend now uses `data.providers.find(p => p.name === field.provider)`. Added `provider` field to `API_KEY_FIELDS`.
**Verified:** `test_get_config_shows_configured_provider` passes.

### BUG-2: POST /api/config ignores providers/gateway fields — FIXED

**Location:** `src/api/routes.py:91-117` and `src/static/js/settings.js:97-109`
**Description:** Frontend sent extra fields but backend only processed thresholds.
**Fix:** Backend now handles API key fields + gateway_url/gateway_key. Frontend sends matching field names.
**Verified:** `test_post_config_updates_api_keys` and `test_post_config_updates_gateway` pass.

### BUG-3: GitHubUsageAdapter class name mismatch (CRITICAL) — FIXED

**Location:** `src/main.py:81`
**Description:** `main.py` imported `"GitHubUsageAdapter"` but actual class is `CopilotUsageAdapter`.
**Fix:** Changed to `"CopilotUsageAdapter"`.
**Verified:** Code review confirmed.

### BUG-4: Static file path mount mismatch (CRITICAL) — FIXED

**Location:** `src/main.py:165-169`
**Description:** StaticFiles mounted at `"/"` but HTML referenced `/static/css/style.css`.
**Fix:** Changed to `app.mount("/static", ...)` + explicit `GET /` route serving `index.html`.
**Verified:** Code review confirmed.

## Threshold Alert Flow (Task #15)

E2E flow verified:
1. `MonitorService.collect_once()` → `SystemSnapshot` (tested)
2. `AlertService.check_system()` → detects warning at 80%, critical at 95% (tested)
3. `AlertService.check_usage()` → detects cost warning at $10, critical at $50 (tested)
4. Alert cooldown (300s) prevents duplicate alerts (tested)
5. `OpenClawNotifier.send_alert()` → HTTP POST to gateway (tested with mock)
6. WebSocket broadcast `{type: "alert", data: AlertEvent}` (shape verified)
7. Frontend `handleAlert()` renders alert with correct level/message (shape verified)

## Test Files

```
tests/
├── __init__.py
├── conftest.py              # Mock adapters, fixtures
├── test_adapters.py         # Psutil, Anthropic, OpenAI, OpenClaw notifier
├── test_alert_service.py    # Threshold detection, cooldown, notification
├── test_api_integration.py  # REST endpoint integration + gateway round-trip
├── test_api_shape.py        # Boundary shape verification
├── test_services.py         # MonitorService, UsageService
└── test_websocket.py        # WS connect/disconnect, subscribe, broadcast, channel filtering
```

## Run Tests

```bash
.venv/bin/python -m pytest tests/ -v
```
