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


def _persist_to_env(settings: Any) -> None:
    """Write current settings to .env so they survive restarts."""
    from src.config import Settings

    # Only persist real Settings objects, not test mocks
    if not isinstance(settings, Settings):
        return

    lines: dict[str, str] = {}

    # Read existing .env to preserve comments and unknown keys
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, _ = stripped.split("=", 1)
                lines[k.strip()] = line  # keep original line

    # Only persist user-changeable settings (keys, thresholds, gateway)
    env_map = {
        "ANTHROPIC_API_KEY": settings.anthropic_api_key or "",
        "ANTHROPIC_API_KEY_REGULAR": settings.anthropic_api_key_regular or "",
        "OPENAI_API_KEY": settings.openai_api_key or "",
        "GITHUB_TOKEN": settings.github_token or "",
        "ZHIPUAI_API_KEY": settings.zhipuai_api_key or "",
        "GEMINI_API_KEY": settings.gemini_api_key or "",
        "THRESHOLDS": json.dumps(
            [dataclasses.asdict(t) for t in settings.thresholds]
        ),
        "ANTHROPIC_SESSION_LIMIT": str(settings.anthropic_session_limit or ""),
        "ANTHROPIC_WEEKLY_LIMIT": str(settings.anthropic_weekly_limit or ""),
        "MONTHLY_BUDGET_USD": str(settings.monthly_budget_usd or ""),
        "OPENCLAW_GATEWAY_URL": settings.openclaw_gateway_url or "",
        "OPENCLAW_API_KEY": settings.openclaw_api_key or "",
    }

    for k, v in env_map.items():
        lines[k] = f"{k}={v}"

    _ENV_PATH.write_text("\n".join(lines.values()) + "\n")


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
    settings = request.app.state.settings
    snapshot = svc.latest
    if snapshot is None:
        return {"timestamp": None, "usages": [], "total_cost_usd": None, "budget": None}
    result = _to_dict(snapshot)
    budget = settings.monthly_budget_usd
    if budget and snapshot.total_cost_usd is not None:
        result["budget"] = {
            "limit_usd": budget,
            "used_usd": snapshot.total_cost_usd,
            "used_percent": round(snapshot.total_cost_usd / budget * 100, 1),
        }
    else:
        result["budget"] = None
    return result


@router.get("/alerts")
async def alerts(request: Request) -> list:
    svc = request.app.state.alert_service
    return [_to_dict(a) for a in svc.recent_alerts]


@router.get("/config")
async def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    providers = []
    key_map = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "github": settings.github_token,
        "zhipuai": settings.zhipuai_api_key,
        "gemini": settings.gemini_api_key,
    }
    for name, key in key_map.items():
        providers.append({"name": name, "configured": bool(key)})

    return {
        "thresholds": [_to_dict(t) for t in settings.thresholds],
        "providers": providers,
        "gateway_url": settings.openclaw_gateway_url or "",
        "gateway_configured": bool(settings.openclaw_api_key),
        "monthly_budget_usd": settings.monthly_budget_usd,
        "anthropic_session_limit": settings.anthropic_session_limit,
        "anthropic_weekly_limit": settings.anthropic_weekly_limit,
        "anthropic_regular_configured": bool(settings.anthropic_api_key_regular),
    }


@router.post("/config")
async def update_config(request: Request) -> dict:
    body = await request.json()
    settings = request.app.state.settings
    alert_svc = request.app.state.alert_service
    usage_svc = request.app.state.usage_service

    if "thresholds" in body:
        from src.core.models import ThresholdConfig

        new_thresholds = [ThresholdConfig(**t) for t in body["thresholds"]]
        settings.thresholds = new_thresholds
        alert_svc.update_thresholds(new_thresholds)

    # API key updates
    # Regular API key (rate limits) — handled separately
    if "anthropic_api_key_regular" in body:
        settings.anthropic_api_key_regular = body["anthropic_api_key_regular"] or None

    key_fields = {
        "anthropic_api_key": "anthropic",
        "openai_api_key": "openai",
        "github_token": "github",
        "zhipuai_api_key": "zhipuai",
        "gemini_api_key": "gemini",
    }
    keys_changed = False
    for field, provider in key_fields.items():
        if field in body:
            setattr(settings, field, body[field] or None)
            keys_changed = True
    if keys_changed:
        usage_svc.update_api_keys({
            "anthropic": settings.anthropic_api_key or "",
            "openai": settings.openai_api_key or "",
            "github": settings.github_token or "",
            "zhipuai": settings.zhipuai_api_key or "",
            "gemini": settings.gemini_api_key or "",
        })
        # Trigger immediate collection so the user doesn't wait 60s
        import asyncio
        asyncio.create_task(usage_svc.collect_once())

    # Plan limits
    if "anthropic_session_limit" in body:
        val = body["anthropic_session_limit"]
        settings.anthropic_session_limit = int(val) if val else None
    if "anthropic_weekly_limit" in body:
        val = body["anthropic_weekly_limit"]
        settings.anthropic_weekly_limit = int(val) if val else None

    # Budget
    if "monthly_budget_usd" in body:
        val = body["monthly_budget_usd"]
        settings.monthly_budget_usd = float(val) if val else None

    # Gateway settings
    if "gateway_url" in body:
        settings.openclaw_gateway_url = body["gateway_url"] or None
    if "gateway_key" in body:
        settings.openclaw_api_key = body["gateway_key"] or None

    # Persist to .env so settings survive restarts
    _persist_to_env(settings)

    return {"status": "updated"}


@router.get("/claude-web-usage")
async def claude_web_usage(request: Request) -> Any:
    """Return Claude.ai web usage scraped via CDP."""
    svc = request.app.state.usage_service
    data = svc.claude_web_latest
    if data is None:
        return {"error": "no data yet (CDP Chrome running?)", "data": None}
    return {"data": data.to_dict()}


@router.get("/ratelimits")
async def ratelimits(request: Request) -> dict:
    """Return Anthropic plan usage (session 5h + weekly)."""
    settings = request.app.state.settings
    key = settings.anthropic_api_key
    if not key:
        return {"error": "anthropic admin key not configured", "anthropic": None}
    from src.adapters.ai_usage.anthropic_plan_usage import fetch_plan_usage
    info = await fetch_plan_usage(
        admin_key=key,
        session_limit=settings.anthropic_session_limit,
        weekly_limit=settings.anthropic_weekly_limit,
    )
    if info is None:
        return {"error": "failed to fetch plan usage", "anthropic": None}
    return {"anthropic": info.to_dict()}


@router.post("/usage/refresh")
async def refresh_usage(request: Request) -> dict:
    """Force an immediate usage collection and return diagnostics."""
    usage_svc = request.app.state.usage_service
    settings = request.app.state.settings

    keys = {
        "anthropic": settings.anthropic_api_key or "",
        "openai": settings.openai_api_key or "",
        "github": settings.github_token or "",
        "zhipuai": settings.zhipuai_api_key or "",
        "gemini": settings.gemini_api_key or "",
    }
    configured = {k: bool(v) for k, v in keys.items()}

    # Collect per-adapter with error details — bypass adapter error handling
    import httpx
    errors = {}
    all_usages = []
    raw_responses = {}
    for adapter in usage_svc._adapters:
        provider = adapter.provider_name()
        api_key = keys.get(provider)
        if not api_key:
            continue
        try:
            usages = await adapter.fetch_usage(api_key)
            all_usages.extend(usages)
            if not usages:
                # No results — probe the raw HTTP response for diagnostics
                if provider == "anthropic":
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc)
                        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                        resp = await client.get(
                            f"{adapter.BASE_URL}/usage_report/messages",
                            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                            params={"start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "end_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "group_by": "model", "time_bucket": "none"},
                        )
                        raw_responses[provider] = {
                            "status": resp.status_code,
                            "body": resp.json() if resp.status_code < 500 else resp.text[:500],
                        }
        except Exception as exc:
            errors[provider] = str(exc)

    # Also do normal collect
    try:
        snapshot = await usage_svc.collect_once()
    except Exception:
        snapshot = None

    return {
        "configured_providers": configured,
        "adapters_loaded": len(usage_svc._adapters),
        "usages_returned": len(all_usages),
        "errors": errors,
        "raw_responses": raw_responses,
        "data": _to_dict(snapshot) if snapshot else None,
    }
