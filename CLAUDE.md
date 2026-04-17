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

## Server Startup
- Always start the server with `bash run.sh`, not `python src/main.py` or `python3 src/main.py`
- `run.sh` creates `.venv` if needed, installs deps, and runs via `.venv/bin/python` — avoids `python` not found errors on macOS

## Behavior Rules (Project-Specific)
- **Trust dashboard values**: When user asks about a dashboard value, do not contradict it with raw CLI tool output (df, free, etc.). Explain how our code calculates the value first.
- **Do not pkill debug Chrome**: Debug Chrome runs as a separate instance. Never kill Chrome processes with pkill.

## Chrome Launch
- To launch a **visible** Chrome window with a specific profile (e.g. for login), use the binary directly — `open -a` just opens a tab in the already-running Chrome:
  ```
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --user-data-dir="$HOME/.tiny-monitor/chrome-debug-profile" \
    --remote-debugging-port=9222 \
    "https://target-url.com" &
  ```
- Debug profile: `~/.tiny-monitor/chrome-debug-profile`, CDP port: `9222`
