# Agentic Dev Gauge

A real-time dashboard for monitoring system resources and AI coding agent quota usage at a glance. Built for developers who juggle multiple AI coding assistants (Claude, GitHub Copilot, ZhipuAI, Codex, local LLMs) and need to keep an eye on usage limits.

![Dashboard Screenshot](docs/screenshot.png)

## What It Monitors

### System Resources
- **CPU**, **Memory** (GB), **Disk** (GB) — via psutil (cross-platform)
- Optional **macmon** backend for richer Apple Silicon metrics (macOS only)

### AI Coding Agent Quotas
Every adapter is **optional** — if a key/login is missing, that card simply doesn't render.

| Provider | Method | What you need |
|---|---|---|
| Claude | CDP scraping of `claude.ai/settings/usage` | Logged-in Chrome debug profile |
| GitHub Copilot | Internal API | `gh auth login` |
| Codex (ChatGPT) | CDP cookie + JWT from `chatgpt.com` | Logged-in Chrome debug profile |
| ZhipuAI GLM | REST API | `ZHIPUAI_API_KEY` |
| Ollama (local) | `/api/ps` + benchmark | Ollama running, model loaded |
| LM Studio (local) | `/api/v0/models` + benchmark | LM Studio server running, model loaded |

All metrics stream via WebSocket with color-coded warning (orange ≥80%) and critical (red ≥90%) thresholds.

## Quick Start

### Prerequisites
- **Python 3.14**
- **macOS** is the primary target. The dashboard runs on Linux/Windows but `macmon`, the Chrome auto-launch flow, and `run.sh` (zsh/bash) are macOS-tuned.
- **Google Chrome** — required only if you want Claude or Codex usage (CDP scraping)
- **`gh` CLI** authenticated — required only for the Copilot card

### Install & Run

```bash
git clone https://github.com/jaydenchoe/agentic-dev-gauge.git
cd agentic-dev-gauge
cp .env.example .env             # fill in keys you actually have
bash run.sh                      # creates .venv, installs deps, runs uvicorn
```

`run.sh` handles venv creation and dependency install — using it avoids `python` vs `python3` and PATH issues on macOS. The dashboard opens automatically in Chrome `--app` mode at `http://localhost:8080`.

### Enabling Claude / Codex usage cards

The Claude and Codex cards scrape a logged-in Chrome session over the Chrome DevTools Protocol. On first launch the server spawns a dedicated debug-profile Chrome at `~/.tiny-monitor/chrome-debug-profile` on port `9222`. **Log in to claude.ai (and chatgpt.com if you want Codex) inside that window once** — the cards will populate within ~5 minutes.

To disable auto-launch and manage Chrome yourself:

```
CHROME_DEBUG_AUTO_LAUNCH=false
```

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ZHIPUAI_API_KEY` | — | ZhipuAI GLM quota |
| `CODEX_API_KEY` | — | Codex bearer (alternative to CDP) |
| `THRESHOLDS` | sane defaults | JSON array of warning/critical thresholds |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234` | LM Studio endpoint |
| `OPENCLAW_GATEWAY_URL` / `OPENCLAW_API_KEY` | — | Alert notifications (optional) |
| `GEEKMAGIC_ULTRA_URL` | blank | GeekMagic SmallTV Ultra external display (optional) |
| `CHROME_DEBUG_PORT` | `9222` | CDP port |
| `CHROME_DEBUG_AUTO_LAUNCH` | `true` | Spawn debug Chrome on startup |

### Settings UI

Click the gear icon to edit thresholds, API keys, Ollama / LM Studio / Gateway / GeekMagic URLs without restarting.

## Architecture

Built on **Hexagonal Architecture** (Ports & Adapters):

```
src/
  core/          # Domain models, Port (ABC) interfaces
  services/      # MonitorService, UsageService, AlertService
  adapters/      # Implementations: system/, ai_usage/, notification/, display/
  api/           # REST routes, WebSocket endpoints
  static/        # Frontend (vanilla JS + CSS, no framework)
```

### Tech Stack
- **Backend**: Python 3.14, FastAPI, uvicorn, pydantic-settings
- **Frontend**: Vanilla JS + CSS
- **System metrics**: psutil (+ macmon on Apple Silicon)
- **Real-time**: WebSocket
- **HTTP client**: httpx (async)

## Features

- Real-time WebSocket streaming (2s system metrics, 60s usage updates)
- Local LLM cards render dynamically — appear when a model loads, disappear when it unloads
- TTFT, prefill tok/s, decode tok/s, and context size for local LLMs
- Chrome `--app` mode auto-launch (macOS) with duplicate-window detection
- Configurable warning/critical thresholds
- Optional alert push via OpenClaw Gateway and external GeekMagic SmallTV Ultra display
- Responsive layout optimized for 960x540 mini monitors up to iPad

## License

MIT
