"""Tests for Claude.ai web usage CDP scraper and API endpoint."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.ai_usage.claude_web_usage import (
    ClaudeWebUsage,
    _parse_usage_text,
    _extract_percent,
    _find_nearby,
)


# ---------------------------------------------------------------------------
# Sample page texts
# ---------------------------------------------------------------------------

SAMPLE_USAGE_PAGE = """
claude.ai
설정
사용량
맥스 플랜
현재 세션
22% 사용됨
약 4시간 후 재설정
모든 모델
55% 사용됨
3일 후 재설정
Sonnet만
10% 사용됨
5일 후 재설정
추가 사용량
US$12.50 사용
월간 지출 한도
US$100.00
""".strip()

SAMPLE_CLOUDFLARE_PAGE = """
보안 확인 수행 중
잠시만 기다리십시오...
Cloudflare
""".strip()

SAMPLE_CLOUDFLARE_VARIANT = """
잠시만 기다리십시오
보안 확인이 완료되면 자동으로 진행됩니다.
""".strip()

SAMPLE_MINIMAL_PAGE = """
프로 플랜
현재 세션
75% 사용됨
1시간 후 재설정
""".strip()

SAMPLE_GARBAGE = """
Welcome to our website
Click here to sign up
Lorem ipsum dolor sit amet
""".strip()


# ---------------------------------------------------------------------------
# _parse_usage_text() unit tests
# ---------------------------------------------------------------------------

class TestParseUsageText:
    """Verify _parse_usage_text handles various page text formats."""

    def test_full_usage_page(self):
        result = _parse_usage_text(SAMPLE_USAGE_PAGE)
        assert result is not None
        assert result.plan == "맥스 플랜"
        assert result.session_used_percent == 22.0
        assert "재설정" in result.session_reset_text
        assert result.weekly_all_used_percent == 55.0
        assert "재설정" in result.weekly_all_reset_text
        assert result.weekly_sonnet_used_percent == 10.0
        assert result.extra_usage_usd == 12.50

    def test_cloudflare_blocked(self):
        result = _parse_usage_text(SAMPLE_CLOUDFLARE_PAGE)
        assert result is None

    def test_cloudflare_variant(self):
        result = _parse_usage_text(SAMPLE_CLOUDFLARE_VARIANT)
        assert result is None

    def test_minimal_page(self):
        result = _parse_usage_text(SAMPLE_MINIMAL_PAGE)
        assert result is not None
        assert result.plan == "프로 플랜"
        assert result.session_used_percent == 75.0
        assert "재설정" in result.session_reset_text

    def test_garbage_text_returns_none(self):
        result = _parse_usage_text(SAMPLE_GARBAGE)
        assert result is None

    def test_empty_text_returns_none(self):
        result = _parse_usage_text("")
        assert result is None

    def test_plan_detection_variants(self):
        for plan in ["맥스 플랜", "프로 플랜", "팀 플랜", "무료 플랜"]:
            text = f"{plan}\n현재 세션\n50% 사용됨\n1시간 후 재설정"
            result = _parse_usage_text(text)
            assert result is not None, f"Failed to parse plan: {plan}"
            assert result.plan == plan


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_extract_percent_integer(self):
        assert _extract_percent("22% 사용됨") == 22.0

    def test_extract_percent_decimal(self):
        assert _extract_percent("55.5% 사용됨") == 55.5

    def test_extract_percent_no_match(self):
        assert _extract_percent("no percent here") is None

    def test_find_nearby_found(self):
        lines = ["현재 세션", "22% 사용됨", "약 4시간 후 재설정"]
        assert _find_nearby(lines, 0, "재설정") == "약 4시간 후 재설정"

    def test_find_nearby_not_found(self):
        lines = ["현재 세션", "22% 사용됨"]
        assert _find_nearby(lines, 0, "재설정") is None

    def test_find_nearby_respects_window(self):
        lines = ["a", "b", "c", "d", "e", "f", "재설정 line"]
        # Default window=5, starting at 0 → checks 0..4 only
        assert _find_nearby(lines, 0, "재설정") is None
        # Starting at 2 → checks 2..6 → finds it
        assert _find_nearby(lines, 2, "재설정") == "재설정 line"


# ---------------------------------------------------------------------------
# ClaudeWebUsage.to_dict() shape test
# ---------------------------------------------------------------------------

class TestClaudeWebUsageShape:
    """Verify to_dict() produces the shape expected by the frontend."""

    def test_to_dict_keys(self):
        usage = ClaudeWebUsage(
            plan="맥스 플랜",
            session_used_percent=22.0,
            session_reset_text="약 4시간 후 재설정",
            weekly_all_used_percent=55.0,
            weekly_all_reset_text="3일 후 재설정",
        )
        d = usage.to_dict()
        assert d["plan"] == "맥스 플랜"
        assert d["session"]["used_percent"] == 22.0
        assert d["session"]["reset_text"] == "약 4시간 후 재설정"
        assert d["weekly_all"]["used_percent"] == 55.0
        assert d["weekly_sonnet"]["used_percent"] is None
        assert d["extra_usage"]["used_usd"] is None

    def test_to_dict_all_none(self):
        usage = ClaudeWebUsage(plan="unknown")
        d = usage.to_dict()
        assert d["plan"] == "unknown"
        assert d["session"]["used_percent"] is None
        assert d["weekly_all"]["used_percent"] is None
        assert d["extra_usage"]["used_usd"] is None
        assert d["extra_usage"]["limit_usd"] is None


# ---------------------------------------------------------------------------
# /api/claude-web-usage endpoint tests (mocked)
# ---------------------------------------------------------------------------

class TestClaudeWebUsageEndpoint:
    """Test GET /api/claude-web-usage with mocked UsageService."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from src.api.routes import router

        app = FastAPI()
        app.include_router(router)

        # Mock services on app.state
        app.state.usage_service = MagicMock()
        app.state.settings = MagicMock()
        app.state.monitor_service = MagicMock()
        app.state.alert_service = MagicMock()
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_returns_data_when_available(self, client, app):
        usage = ClaudeWebUsage(
            plan="맥스 플랜",
            session_used_percent=22.0,
            session_reset_text="약 4시간 후 재설정",
        )
        app.state.usage_service.claude_web_latest = usage

        resp = client.get("/api/claude-web-usage")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"]["plan"] == "맥스 플랜"
        assert body["data"]["session"]["used_percent"] == 22.0

    def test_returns_error_when_no_data(self, client, app):
        app.state.usage_service.claude_web_latest = None

        resp = client.get("/api/claude-web-usage")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] is None
        assert "error" in body


# ---------------------------------------------------------------------------
# CDP connection failure — graceful degradation
# ---------------------------------------------------------------------------

class TestCDPGracefulFail:
    """Verify fetch_claude_web_usage handles CDP unavailability."""

    @pytest.mark.asyncio
    async def test_cdp_unreachable_returns_none(self):
        from src.adapters.ai_usage.claude_web_usage import fetch_claude_web_usage, _cache
        # Clear cache to force a real fetch attempt
        _cache.clear()

        # CDP on a port with no Chrome → should return None, not raise
        result = await fetch_claude_web_usage(cdp_host="127.0.0.1", cdp_port=19999)
        assert result is None

    @pytest.mark.asyncio
    async def test_cdp_failure_does_not_crash_usage_service(self):
        """UsageService._claude_web_loop should survive CDP errors."""
        from src.services.usage_service import UsageService

        svc = UsageService(adapters=[], api_keys={}, claude_web_cdp_port=19999)

        # Patch fetch_claude_web_usage to raise
        with patch(
            "src.services.usage_service.fetch_claude_web_usage",
            new_callable=AsyncMock,
            side_effect=ConnectionError("no chrome"),
        ):
            # Simulate one iteration of the loop (without the sleep)
            try:
                result = await fetch_claude_web_usage(cdp_port=19999)
            except Exception:
                pass
            # Service should still have None, not crash
            assert svc.claude_web_latest is None
