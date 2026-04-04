# CLAUDE.md — Agentic Dev Gauge

## Project Overview
Real-time web dashboard monitoring system resources (CPU, RAM, Disk) and AI coding agent quota usage (Claude, GitHub Copilot, ZhipuAI, Ollama). Built on Hexagonal Architecture (Ports & Adapters).

## Tech Stack
- Backend: Python 3.14, FastAPI, uvicorn, pydantic-settings
- Frontend: Vanilla JS + CSS (no framework)
- System metrics: psutil
- Real-time: WebSocket
- External API: httpx (async)

## Directory Structure
```
src/
  core/          # Domain models, Port (ABC) interfaces
  services/      # MonitorService, UsageService, AlertService
  adapters/      # Port implementations (system/, ai_usage/, notification/)
  api/           # REST routes, WebSocket endpoints
  static/        # Frontend (HTML, CSS, JS)
tests/           # pytest tests
_workspace/      # Architecture docs, QA reports
```

## Coding Conventions
- All adapters must implement Core Port (ABC) interfaces
- External API calls must be async (httpx)
- Core domain must not know about external dependencies (Hexagonal principle)

## Behavior Rules (Project-Specific)
- **Trust dashboard values**: When user asks about a dashboard value, do not contradict it with raw CLI tool output (df, free, etc.). Explain how our code calculates the value first.
- **Do not pkill debug Chrome**: Debug Chrome runs as a separate instance. Never kill Chrome processes with pkill.
