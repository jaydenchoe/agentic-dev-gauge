"""Tiny Monitor — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

# Ensure project root is on sys.path so `from src.…` imports work
# when running as `python src/main.py`.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as api_router
from src.api.websocket import router as ws_router, run_broadcast_loop
from src.config import Settings
from src.core.ports.metrics import MetricsPort
from src.core.ports.notification import NotificationPort
from src.core.ports.usage import UsagePort
from src.chrome_launcher import launch_debug_chrome, shutdown_debug_chrome
from src.services.alert_service import AlertService
from src.services.monitor_service import MonitorService
from src.services.usage_service import UsageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tiny-monitor")


# ---------------------------------------------------------------------------
# Adapter discovery
# ---------------------------------------------------------------------------

def _build_metrics_adapter(settings: Settings) -> MetricsPort:
    """Select the best available system metrics adapter."""
    backend = settings.metrics_backend

    # Always try to build psutil first as the base adapter.
    psutil_adapter: MetricsPort | None = None
    try:
        from src.adapters.system.psutil_adapter import PsutilMetricsAdapter
        psutil_adapter = PsutilMetricsAdapter()
    except (ImportError, AttributeError):
        if backend == "psutil":
            raise
        logger.info("psutil not available")

    if backend in ("auto", "macmon"):
        try:
            from src.adapters.system.macmon_adapter import MacmonMetricsAdapter
            import shutil
            if shutil.which("macmon") is not None:
                adapter = MacmonMetricsAdapter(psutil_adapter=psutil_adapter)
                logger.info("Using macmon metrics adapter (with psutil base)")
                return adapter
            else:
                logger.info("macmon CLI not found, skipping")
        except (ImportError, AttributeError):
            if backend == "macmon":
                raise
            logger.info("macmon not available, falling back")

    if psutil_adapter is not None:
        logger.info("Using psutil metrics adapter")
        return psutil_adapter

    # Fallback: mock adapter so the server can still start
    from src.adapters.system.mock_adapter import MockMetricsAdapter
    logger.warning("No system metrics adapter available — using mock")
    return MockMetricsAdapter()


def _build_usage_adapters() -> list[UsagePort]:
    """Discover available AI usage adapters (best-effort)."""
    adapters: list[UsagePort] = []
    adapter_classes: list[tuple[str, str]] = [
        ("src.adapters.ai_usage.anthropic_adapter", "AnthropicUsageAdapter"),
        ("src.adapters.ai_usage.openai_adapter", "OpenAIUsageAdapter"),
        ("src.adapters.ai_usage.github_adapter", "CopilotUsageAdapter"),
        ("src.adapters.ai_usage.zhipuai_adapter", "ZhipuAIUsageAdapter"),
        ("src.adapters.ai_usage.gemini_adapter", "GeminiUsageAdapter"),
    ]
    for module_path, class_name in adapter_classes:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            cls = getattr(mod, class_name)
            adapters.append(cls())
        except (ImportError, AttributeError):
            pass
    return adapters


def _build_notifier(settings: Settings) -> NotificationPort | None:
    if not settings.openclaw_gateway_url:
        return None
    try:
        from src.adapters.notification.openclaw_notifier import OpenClawNotifier
        return OpenClawNotifier(
            gateway_url=settings.openclaw_gateway_url,
            api_key=settings.openclaw_api_key,
        )
    except (ImportError, AttributeError):
        logger.warning("OpenClaw notifier not available")
        return None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    app.state.settings = settings

    # Launch debug Chrome for CDP scraping
    chrome_proc = None
    if settings.chrome_debug_auto_launch:
        chrome_proc = await launch_debug_chrome(
            profile_dir=settings.chrome_debug_profile_dir,
            port=settings.chrome_debug_port,
        )

    # Build adapters
    metrics_adapter = _build_metrics_adapter(settings)
    usage_adapters = _build_usage_adapters()
    notifier = _build_notifier(settings)

    # Build services
    monitor_svc = MonitorService(metrics_adapter, interval=settings.metrics_interval_sec)
    api_keys = {
        "anthropic": settings.anthropic_api_key or "",
        "openai": settings.openai_api_key or "",
        "github": settings.github_token or "",
        "zhipuai": settings.zhipuai_api_key or "",
        "gemini": settings.gemini_api_key or "",
    }
    usage_svc = UsageService(
        usage_adapters, api_keys,
        interval=settings.usage_interval_sec,
        claude_web_cdp_port=settings.claude_web_cdp_port,
        claude_web_interval=settings.claude_web_interval_sec,
    )
    alert_svc = AlertService(settings.thresholds, notifier)

    app.state.monitor_service = monitor_svc
    app.state.usage_service = usage_svc
    app.state.alert_service = alert_svc

    # Start background collection
    monitor_svc.start()
    usage_svc.start()
    broadcast_task = asyncio.create_task(run_broadcast_loop(app))

    logger.info("Tiny Monitor started on %s:%s", settings.host, settings.port)
    yield

    # Shutdown
    broadcast_task.cancel()
    await monitor_svc.stop()
    await usage_svc.stop()
    shutdown_debug_chrome(chrome_proc)
    logger.info("Tiny Monitor stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Tiny Monitor", lifespan=lifespan)
app.include_router(api_router)
app.include_router(ws_router)

# Serve static files (frontend)
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(str(_static_dir / "index.html"))

    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


if __name__ == "__main__":
    import uvicorn

    _settings = Settings()
    uvicorn.run(
        "src.main:app",
        host=_settings.host,
        port=_settings.port,
        reload=False,
    )
