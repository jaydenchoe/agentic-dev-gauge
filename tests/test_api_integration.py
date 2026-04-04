"""Integration tests for API endpoints using FastAPI TestClient."""

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import router as api_router
from src.core.models import ThresholdConfig, UsageSnapshot
from src.services.alert_service import AlertService
from src.services.monitor_service import MonitorService
from src.services.usage_service import UsageService
from tests.conftest import MockMetricsAdapter, MockUsageAdapter, MockNotifier, make_snapshot


@pytest.fixture
def app(default_thresholds):
    """Build a test FastAPI app with mock services."""
    app = FastAPI()
    app.include_router(api_router)

    metrics_adapter = MockMetricsAdapter()
    usage_adapter = MockUsageAdapter(provider="anthropic")
    notifier = MockNotifier()

    monitor_svc = MonitorService(metrics_adapter, interval=2.0)
    usage_svc = UsageService(
        adapters=[usage_adapter],
        api_keys={"anthropic": "test-key"},
    )
    alert_svc = AlertService(default_thresholds, notifier)

    app.state.monitor_service = monitor_svc
    app.state.usage_service = usage_svc
    app.state.alert_service = alert_svc
    app.state.settings = SimpleNamespace(
        thresholds=default_thresholds,
        codex_api_key="codex-test-key",
        zhipuai_api_key=None,
        openclaw_gateway_url=None,
        openclaw_api_key=None,
    )

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def test_metrics_503_when_no_data(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 503

    def test_metrics_returns_snapshot(self, app, client):
        # Pre-populate latest snapshot directly
        from tests.conftest import make_snapshot
        app.state.monitor_service._latest = make_snapshot()

        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()

        # Verify shape matches frontend expectations
        assert "cpu" in data
        assert "usage_percent" in data["cpu"]
        assert "per_core" in data["cpu"]
        assert "memory" in data
        assert "usage_percent" in data["memory"]
        assert "disk" in data
        assert "network" in data
        assert "bytes_sent_per_sec" in data["network"]


# ---------------------------------------------------------------------------
# Usage endpoint
# ---------------------------------------------------------------------------

class TestUsageEndpoint:
    def test_usage_empty_when_no_data(self, client):
        resp = client.get("/api/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["usages"] == []
        assert data["total_cost_usd"] is None

    def test_usage_returns_data(self, app, client):
        from datetime import datetime, timezone
        from src.core.models import UsageSnapshot, TokenUsage
        app.state.usage_service._latest = UsageSnapshot(
            timestamp=datetime.now(timezone.utc),
            usages=[TokenUsage(
                provider="anthropic", model="test", input_tokens=1000,
                output_tokens=500, total_tokens=1500, cost_usd=0.05,
            )],
            total_cost_usd=0.05,
        )

        resp = client.get("/api/usage")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["usages"]) == 1
        assert data["usages"][0]["provider"] == "anthropic"
        assert data["usages"][0]["total_tokens"] == 1500
        assert "total_cost_usd" in data


# ---------------------------------------------------------------------------
# Alerts endpoint
# ---------------------------------------------------------------------------

class TestAlertsEndpoint:
    def test_alerts_empty_initially(self, client):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_alerts_after_threshold_breach(self, app, client):
        from datetime import datetime, timezone
        from src.core.models import AlertEvent
        # Directly add an alert to the service
        event = AlertEvent(
            timestamp=datetime.now(timezone.utc),
            metric="cpu_percent",
            current_value=90.0,
            threshold=80.0,
            level="warning",
            message="CPU usage high",
        )
        app.state.alert_service._recent_alerts.append(event)

        resp = client.get("/api/alerts")
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["metric"] == "cpu_percent"
        assert data[0]["level"] == "warning"


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------

class TestConfigEndpoint:
    def test_get_config_shape(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()

        assert "thresholds" in data
        assert "providers" in data
        assert isinstance(data["thresholds"], list)
        assert isinstance(data["providers"], list)

        # Each threshold has metric, warning, critical
        for t in data["thresholds"]:
            assert "metric" in t
            assert "warning" in t
            assert "critical" in t

        # Each provider has name, configured
        for p in data["providers"]:
            assert "name" in p
            assert "configured" in p

        # Gateway fields present (BUG-2 fix verification)
        assert "gateway_url" in data
        assert "gateway_configured" in data

    def test_get_config_shows_configured_provider(self, client):
        """Verify that providers with API keys show configured=True."""
        resp = client.get("/api/config")
        data = resp.json()
        codex = next(p for p in data["providers"] if p["name"] == "codex")
        assert codex["configured"] is True
        zhipuai = next(p for p in data["providers"] if p["name"] == "zhipuai")
        assert zhipuai["configured"] is False

    def test_post_config_updates_thresholds(self, client):
        new_config = {
            "thresholds": [
                {"metric": "cpu_percent", "warning": 70, "critical": 90},
            ]
        }
        resp = client.post("/api/config", json=new_config)
        assert resp.status_code == 200
        assert resp.json() == {"status": "updated"}

    def test_post_config_updates_api_keys(self, app, client):
        """Verify API key updates are applied to runtime settings."""
        resp = client.post("/api/config", json={
            "codex_api_key": "codex-new-key",
            "zhipuai_api_key": "zhipu-new-key",
        })
        assert resp.status_code == 200
        assert app.state.settings.codex_api_key == "codex-new-key"
        assert app.state.settings.zhipuai_api_key == "zhipu-new-key"

    def test_post_config_persists_api_keys_to_env(self, monkeypatch, app, client, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# existing config\n"
            "THRESHOLDS=[{\"metric\":\"cpu_percent\",\"warning\":80,\"critical\":95}]\n"
            "OPENCLAW_GATEWAY_URL=https://gw.example.com\n"
            "CODEX_API_KEY=old-codex-key\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("src.api.routes._ENV_PATH", env_path)

        resp = client.post("/api/config", json={
            "codex_api_key": "codex-new-key",
            "zhipuai_api_key": "zhipu-new-key",
        })

        assert resp.status_code == 200

        env_text = env_path.read_text(encoding="utf-8")
        assert "# existing config" in env_text
        assert "THRESHOLDS=[{\"metric\":\"cpu_percent\",\"warning\":80,\"critical\":95}]" in env_text
        assert "OPENCLAW_GATEWAY_URL=https://gw.example.com" in env_text
        assert "CODEX_API_KEY=codex-new-key" in env_text
        assert "CODEX_API_KEY=old-codex-key" not in env_text
        assert "ZHIPUAI_API_KEY=zhipu-new-key" in env_text

    def test_post_config_updates_gateway(self, app, client):
        """Verify gateway URL/key update (BUG-2 fix)."""
        resp = client.post("/api/config", json={
            "gateway_url": "https://gw.example.com",
            "gateway_key": "gw-key-123",
        })
        assert resp.status_code == 200
        assert app.state.settings.openclaw_gateway_url == "https://gw.example.com"
        assert app.state.settings.openclaw_api_key == "gw-key-123"

    def test_gateway_config_round_trip(self, app, client):
        """POST gateway config then GET to confirm persistence."""
        # Initially no gateway
        resp = client.get("/api/config")
        data = resp.json()
        assert data["gateway_url"] == ""
        assert data["gateway_configured"] is False

        # Update gateway settings
        client.post("/api/config", json={
            "gateway_url": "https://gw.test.io",
            "gateway_key": "secret-gw-key",
        })

        # GET should reflect the update
        resp = client.get("/api/config")
        data = resp.json()
        assert data["gateway_url"] == "https://gw.test.io"
        assert data["gateway_configured"] is True

    def test_gateway_url_clear(self, app, client):
        """Setting gateway_url to empty string should clear it."""
        # Set then clear
        client.post("/api/config", json={"gateway_url": "https://gw.io"})
        client.post("/api/config", json={"gateway_url": ""})

        resp = client.get("/api/config")
        data = resp.json()
        assert data["gateway_url"] == ""
        assert app.state.settings.openclaw_gateway_url is None
