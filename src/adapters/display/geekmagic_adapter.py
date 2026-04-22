"""GeekMagicDisplayAdapter — push 240x240 PNG images to a GeekMagic SmallTV Ultra."""

from __future__ import annotations

import asyncio
import ipaddress
import logging

import httpx

from src.core.ports.display import DisplayPort

logger = logging.getLogger(__name__)

_MALFORMED_MARKERS = ("Duplicate Content-Length", "Data after")


class GeekMagicDisplayAdapter(DisplayPort):
    """POST rendered PNG frames to a GeekMagic SmallTV Ultra (ESP8266, 240x240)."""

    UPLOAD_FILENAME = "tm.gif"
    UPLOAD_DIR = "/image/"
    ULTRA_THEME = 3

    def __init__(self, base_url: str, timeout_sec: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_sec
        self._theme_set = False
        self._push_failures = 0

    def set_base_url(self, base_url: str) -> None:
        new_base = base_url.rstrip("/")
        if new_base != self._base_url:
            self._base_url = new_base
            self._theme_set = False
            self._push_failures = 0

    async def _auto_discover(self) -> bool:
        try:
            host = httpx.URL(self._base_url).host
            current_ip = ipaddress.ip_address(host if host is not None else "")
        except ValueError:
            logger.warning(
                "GeekMagic auto-discovery skipped for non-IP base URL: %s",
                self._base_url,
            )
            return False

        if not isinstance(current_ip, ipaddress.IPv4Address):
            logger.warning(
                "GeekMagic auto-discovery skipped for non-IPv4 base URL: %s",
                self._base_url,
            )
            return False

        subnet_prefix = ".".join(str(current_ip).split(".")[:3])
        async def _probe(client: httpx.AsyncClient, ip: str) -> bool:
            url = f"http://{ip}"
            try:
                r = await client.get(f"{url}/set?theme={self.ULTRA_THEME}")
                # GeekMagic firmware responds with exactly "OK"
                return r.status_code == 200 and r.text.strip() == "OK"
            except Exception:
                return False

        async with httpx.AsyncClient(timeout=0.5) as client:
            tasks = {
                f"{subnet_prefix}.{i}": asyncio.create_task(_probe(client, f"{subnet_prefix}.{i}"))
                for i in range(1, 255)
            }
            for ip, task in tasks.items():
                try:
                    if await task:
                        for t in tasks.values():
                            t.cancel()
                        self._base_url = f"http://{ip}"
                        self._theme_set = True
                        logger.info("GeekMagic auto-discovered at %s", ip)
                        return True
                except Exception:
                    continue

        return False

    async def _handle_push_failure(self) -> bool:
        self._theme_set = False
        self._push_failures += 1
        if self._push_failures >= 3:
            await self._auto_discover()
            self._push_failures = 0
        return False

    async def push_png(self, png_bytes: bytes) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if not self._theme_set:
                try:
                    resp = await client.get(
                        f"{self._base_url}/set?theme={self.ULTRA_THEME}"
                    )
                    if 200 <= resp.status_code < 300:
                        self._theme_set = True
                except httpx.HTTPError as exc:
                    logger.debug("GeekMagic theme set deferred: %s", exc)

            files = {"file": (self.UPLOAD_FILENAME, png_bytes, "image/gif")}
            try:
                upload_resp = await client.post(
                    f"{self._base_url}/doUpload?dir={self.UPLOAD_DIR}",
                    files=files,
                )
                if upload_resp.status_code == 405:
                    logger.warning("GeekMagic doUpload 405 — wrong device, triggering rediscovery")
                    return await self._handle_push_failure()
            except httpx.RemoteProtocolError as exc:
                logger.debug(
                    "GeekMagic upload malformed response (firmware bug), continuing: %s",
                    exc,
                )
            except httpx.HTTPError as exc:
                msg = str(exc)
                if any(marker in msg for marker in _MALFORMED_MARKERS):
                    logger.debug(
                        "GeekMagic upload malformed response (firmware bug), continuing: %s",
                        exc,
                    )
                else:
                    logger.warning("GeekMagic upload failed: %s", exc)
                    return await self._handle_push_failure()

            # Firmware stores files at UPLOAD_DIR + "/" + filename (extra slash).
            img_path = f"{self.UPLOAD_DIR}/{self.UPLOAD_FILENAME}"  # e.g. /image//tm.gif
            try:
                resp = await client.get(
                    f"{self._base_url}/set?img={img_path}"
                )
            except httpx.HTTPError as exc:
                logger.warning("GeekMagic /set failed: %s", exc)
                return await self._handle_push_failure()

            if not 200 <= resp.status_code < 300:
                logger.warning(
                    "GeekMagic /set returned %s: %s",
                    resp.status_code,
                    resp.text[:120],
                )
                return await self._handle_push_failure()

            self._push_failures = 0
            return True
