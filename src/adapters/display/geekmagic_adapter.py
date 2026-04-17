"""GeekMagicDisplayAdapter — push 240x240 PNG images to a GeekMagic SmallTV Ultra."""

from __future__ import annotations

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

    def set_base_url(self, base_url: str) -> None:
        new_base = base_url.rstrip("/")
        if new_base != self._base_url:
            self._base_url = new_base
            self._theme_set = False

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
                await client.post(
                    f"{self._base_url}/doUpload?dir={self.UPLOAD_DIR}",
                    files=files,
                )
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
                    return False

            # Firmware stores files at UPLOAD_DIR + "/" + filename (extra slash).
            img_path = f"{self.UPLOAD_DIR}/{self.UPLOAD_FILENAME}"  # e.g. /image//tm.gif
            try:
                resp = await client.get(
                    f"{self._base_url}/set?img={img_path}"
                )
            except httpx.HTTPError as exc:
                logger.warning("GeekMagic /set failed: %s", exc)
                return False

            if not 200 <= resp.status_code < 300:
                logger.warning(
                    "GeekMagic /set returned %s: %s",
                    resp.status_code,
                    resp.text[:120],
                )
                return False

            return True
