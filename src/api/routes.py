"""REST API endpoints."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api")

_start_time = time.time()
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _persist_env_updates(env_updates: dict[str, str]) -> None:
    """Update or append env vars without disturbing other .env lines."""
    if not env_updates:
        return

    lines: list[str] = []
    seen_keys: set[str] = set()
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue

        key, _, _ = line.partition("=")
        env_key = key.strip()
        if env_key in env_updates:
            updated_lines.append(f"{env_key}={env_updates[env_key]}")
            seen_keys.add(env_key)
            continue

        updated_lines.append(line)

    for env_key, value in env_updates.items():
        if env_key not in seen_keys:
            updated_lines.append(f"{env_key}={value}")

    _ENV_PATH.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclass instances to dicts for JSON serialisation."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "uptime_seconds": round(time.time() - _start_time, 1)}


@router.get("/metrics")
async def metrics(request: Request) -> Any:
    svc = request.app.state.monitor_service
    snapshot = svc.latest
    if snapshot is None:
        return JSONResponse({"error": "no data yet"}, status_code=503)
    return _to_dict(snapshot)


@router.get("/usage")
async def usage(request: Request) -> Any:
    svc = request.app.state.usage_service
    snapshot = svc.latest
    if snapshot is None:
        return {"timestamp": None, "usages": [], "total_cost_usd": None}
    return _to_dict(snapshot)


@router.get("/alerts")
async def alerts(request: Request) -> list:
    svc = request.app.state.alert_service
    return [_to_dict(a) for a in svc.recent_alerts]


@router.get("/config")
async def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    providers = [
        {"name": "codex", "configured": bool(settings.codex_api_key)},
        {"name": "zhipuai", "configured": bool(settings.zhipuai_api_key)},
    ]

    return {
        "thresholds": [_to_dict(t) for t in settings.thresholds],
        "providers": providers,
        "gateway_url": settings.openclaw_gateway_url or "",
        "gateway_configured": bool(settings.openclaw_api_key),
    }


@router.post("/config")
async def update_config(request: Request) -> dict:
    body = await request.json()
    settings = request.app.state.settings
    alert_svc = request.app.state.alert_service
    usage_svc = request.app.state.usage_service
    usage_keys_updated = False
    env_updates: dict[str, str] = {}

    if "thresholds" in body:
        from src.core.models import ThresholdConfig

        new_thresholds = [ThresholdConfig(**t) for t in body["thresholds"]]
        settings.thresholds = new_thresholds
        alert_svc.update_thresholds(new_thresholds)
        env_updates["THRESHOLDS"] = json.dumps(
            [dataclasses.asdict(t) for t in settings.thresholds]
        )

    # API key updates
    usage_api_key_fields = {"codex_api_key", "zhipuai_api_key"}
    for field_name in usage_api_key_fields:
        if field_name not in body:
            continue

        setattr(settings, field_name, body[field_name] or None)
        env_updates[field_name.upper()] = getattr(settings, field_name) or ""
        usage_keys_updated = True

    for field_name, value in body.items():
        if field_name in usage_api_key_fields or not field_name.endswith("_api_key"):
            continue
        if not hasattr(settings, field_name):
            continue

        setattr(settings, field_name, value or None)
        env_updates[field_name.upper()] = getattr(settings, field_name) or ""

    if usage_keys_updated:
        usage_svc.update_api_keys({
            "codex": settings.codex_api_key or "",
            "zhipuai": settings.zhipuai_api_key or "",
        })
        import asyncio
        asyncio.create_task(usage_svc.collect_once())

    # Gateway settings
    if "gateway_url" in body:
        settings.openclaw_gateway_url = body["gateway_url"] or None
        env_updates["OPENCLAW_GATEWAY_URL"] = settings.openclaw_gateway_url or ""
    if "gateway_key" in body:
        settings.openclaw_api_key = body["gateway_key"] or None
        env_updates["OPENCLAW_API_KEY"] = settings.openclaw_api_key or ""

    # Persist updated env-backed settings so they survive restarts.
    _persist_env_updates(env_updates)

    return {"status": "updated"}


@router.get("/claude-web-usage")
async def claude_web_usage(request: Request) -> Any:
    """Return Claude.ai web usage scraped via CDP."""
    svc = request.app.state.usage_service
    data = svc.claude_web_latest
    if data is None:
        return {"error": "no data yet (CDP Chrome running?)", "data": None}
    return {"data": data.to_dict()}


@router.get("/copilot-usage")
async def copilot_usage(request: Request) -> Any:
    """Return GitHub Copilot quota from internal API."""
    svc = request.app.state.usage_service
    data = svc.copilot_api_latest
    if data is None:
        return {"error": "no data yet (gh CLI authenticated?)", "data": None}
    return {"data": data.to_dict()}


@router.get("/ollama-usage")
async def ollama_usage(request: Request) -> Any:
    """Return Ollama local LLM status."""
    svc = request.app.state.usage_service
    data = svc.ollama_latest
    if data is None:
        return {"error": "no data yet (Ollama running?)", "data": None}
    return {"data": data.to_dict()}


@router.post("/usage/refresh")
async def refresh_usage(request: Request) -> dict:
    """Force an immediate usage collection and return diagnostics."""
    usage_svc = request.app.state.usage_service

    try:
        snapshot = await usage_svc.collect_once()
    except Exception:
        snapshot = None

    return {
        "adapters_loaded": len(usage_svc._adapters),
        "data": _to_dict(snapshot) if snapshot else None,
    }
