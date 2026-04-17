"""CodexUsageAdapter — fetch ChatGPT Pro Codex quota usage from ChatGPT web API."""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.core.models import TokenUsage
from src.core.ports.usage import UsagePort

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"


class CodexUsageAdapter(UsagePort):
    BASE_URL = "https://chatgpt.com/backend-api/wham/usage"
    DEVICE_ID = "agentic-dev-gauge"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, cdp_host: str = "127.0.0.1", cdp_port: int = 9222) -> None:
        self._cdp_host = cdp_host
        self._cdp_port = cdp_port
        self._renewed_token: str | None = None

    def provider_name(self) -> str:
        return "codex"

    def _check_jwt_expiry(self, token: str) -> str | None:
        """Return 'Token expired (MMM DD)' string if JWT is expired, else None."""
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            if exp and datetime.now(tz=timezone.utc).timestamp() > exp:
                exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
                return f"Token expired ({exp_dt.strftime('%b %d')})"
        except Exception:
            pass
        return None

    async def _renew_token_via_cookie(self) -> str | None:
        """Read chatgpt.com session cookie from Chrome profile and fetch a fresh JWT.

        Reads encrypted cookies from Chrome's SQLite store, decrypts them using
        the macOS Keychain Safe Storage key, then calls /api/auth/session.
        No browser interaction — completely silent.
        """
        cookie_value = self._read_chrome_cookie(".chatgpt.com", "__Secure-next-auth.session-token")
        if not cookie_value:
            logger.warning("Codex: chatgpt.com session cookie not found")
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    "https://chatgpt.com/api/auth/session",
                    headers={"user-agent": self.USER_AGENT},
                    cookies={"__Secure-next-auth.session-token": cookie_value},
                )
                resp.raise_for_status()
                data = resp.json()
                token = data.get("accessToken")
        except Exception as exc:
            logger.warning("Codex: session API call failed: %s", exc)
            return None

        if token:
            logger.info("Codex token renewed via Chrome cookie")
            self._save_token_to_env(token)
        return token or None

    def _read_chrome_cookie(self, host: str, name: str) -> str | None:
        """Read and decrypt a Chrome cookie on macOS."""
        import hashlib
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        cookie_db = (
            Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
        )
        if not cookie_db.exists():
            return None

        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "Chrome Safe Storage", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            chrome_password = result.stdout.strip().encode() or b"peanuts"
        except Exception:
            chrome_password = b"peanuts"

        key = hashlib.pbkdf2_hmac("sha1", chrome_password, b"saltysalt", 1003, dklen=16)

        tmp = tempfile.mktemp(suffix=".db")
        try:
            shutil.copy2(cookie_db, tmp)
            conn = sqlite3.connect(tmp)
            rows = conn.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key=? AND name LIKE ?",
                (host, f"{name}%"),
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Codex: cannot read Chrome cookies: %s", exc)
            return None
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass

        # Collect and sort split cookie parts (e.g. .session-token.0, .session-token.1)
        parts = sorted(rows, key=lambda r: r[0])
        decrypted_parts: list[str] = []
        for _, enc_val in parts:
            if not enc_val:
                continue
            try:
                decrypted_parts.append(self._decrypt_chrome_cookie(enc_val, key))
            except Exception:
                pass

        return "".join(decrypted_parts) or None

    @staticmethod
    def _decrypt_chrome_cookie(encrypted_value: bytes, key: bytes) -> str:
        from Crypto.Cipher import AES

        if encrypted_value[:3] == b"v10":
            iv = b" " * 16
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_value[3:])
            pad = decrypted[-1]
            decrypted = decrypted[:-pad]
            # Chrome prepends a 32-byte integrity header to the plaintext
            return decrypted[32:].decode("utf-8", errors="replace")
        return encrypted_value.decode("utf-8", errors="replace")

    def _save_token_to_env(self, token: str) -> None:
        try:
            text = _ENV_PATH.read_text() if _ENV_PATH.exists() else ""
            for key in ("CODEX_API_KEY", "CODEX_BEARER_TOKEN"):
                if re.search(rf"^{key}=", text, re.MULTILINE):
                    text = re.sub(rf"^{key}=.*$", f"{key}={token}", text, flags=re.MULTILINE)
                else:
                    text += f"\n{key}={token}"
            _ENV_PATH.write_text(text)
            logger.info("Codex token saved to .env")
        except Exception as exc:
            logger.warning("Failed to save Codex token to .env: %s", exc)

    async def fetch_usage(self, api_key: str) -> list[TokenUsage]:
        effective_key = self._renewed_token or api_key

        expired_msg = self._check_jwt_expiry(effective_key)
        if expired_msg:
            logger.warning("Codex JWT expired — attempting cookie renewal")
            new_token = await self._renew_token_via_cookie()
            if new_token:
                self._renewed_token = new_token
                effective_key = new_token
            else:
                return [TokenUsage(
                    provider="codex", model="error",
                    input_tokens=0, output_tokens=0, total_tokens=0,
                    error=expired_msg,
                )]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BASE_URL,
                    headers={
                        "authorization": f"Bearer {effective_key}",
                        "oai-device-id": self.DEVICE_ID,
                        "user-agent": self.USER_AGENT,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Codex usage API error: %s", exc)
            return []

        if not isinstance(data, dict):
            logger.warning("Codex unexpected response type: %s", type(data).__name__)
            return []

        plan_type = data.get("plan_type")
        results: list[TokenUsage] = []

        rate_limit = data.get("rate_limit") or {}
        primary_window = rate_limit.get("primary_window") or {}
        secondary_window = rate_limit.get("secondary_window") or {}

        session_usage = self._build_usage(
            model="session",
            period="5h_rolling",
            window=primary_window,
            plan_type=plan_type,
        )
        if session_usage:
            results.append(session_usage)

        weekly_usage = self._build_usage(
            model="weekly",
            period="weekly",
            window=secondary_window,
            plan_type=plan_type,
        )
        if weekly_usage:
            results.append(weekly_usage)

        additional_limits = data.get("additional_rate_limits") or []
        if additional_limits:
            spark_window = ((additional_limits[0] or {}).get("rate_limit") or {}).get("secondary_window") or {}
            spark_usage = self._build_usage(
                model="spark-weekly",
                period="weekly",
                window=spark_window,
                plan_type=plan_type,
            )
            if spark_usage:
                results.append(spark_usage)

        review_window = (data.get("code_review_rate_limit") or {}).get("primary_window") or {}
        review_usage = self._build_usage(
            model="review",
            period="weekly",
            window=review_window,
            plan_type=plan_type,
        )
        if review_usage:
            results.append(review_usage)

        return results

    def _build_usage(
        self,
        *,
        model: str,
        period: str,
        window: dict,
        plan_type: str | None,
    ) -> TokenUsage | None:
        if not isinstance(window, dict):
            return None

        used_percent = window.get("used_percent")
        if used_percent is None:
            return None

        try:
            quota_percentage = float(used_percent)
        except (TypeError, ValueError):
            return None

        return TokenUsage(
            provider="codex",
            model=model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_usd=None,
            period=period,
            quota_percentage=quota_percentage,
            reset_text=self._format_reset(window.get("reset_at")),
            plan_type=plan_type,
        )

    def _format_reset(self, reset_at: object) -> str | None:
        if reset_at in (None, ""):
            return None

        try:
            if isinstance(reset_at, (int, float)):
                timestamp = float(reset_at)
                if timestamp > 1_000_000_000_000:
                    timestamp /= 1000
                reset_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            elif isinstance(reset_at, str):
                normalized = reset_at.replace("Z", "+00:00")
                reset_dt = datetime.fromisoformat(normalized)
                if reset_dt.tzinfo is None:
                    reset_dt = reset_dt.replace(tzinfo=timezone.utc)
                else:
                    reset_dt = reset_dt.astimezone(timezone.utc)
            else:
                return None
        except (TypeError, ValueError, OSError):
            logger.warning("Codex invalid reset_at value: %s", reset_at)
            return None

        return reset_dt.strftime("%Y-%m-%d %H:%M UTC")
