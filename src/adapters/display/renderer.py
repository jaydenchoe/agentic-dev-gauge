"""Pillow-based renderer for GeekMagic SmallTV Ultra (240x240) dashboard frames."""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

SIZE = 240

BG = "#0A0A0A"
CARD = "#1A1A1A"
BAR_BG = "#262626"
TEXT = "#E5E5E5"
SUBTEXT = "#9CA3AF"

OK = "#10B981"
WARN = "#F59E0B"
HIGH = "#F97316"
CRIT = "#EF4444"

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)
_FONT_SIZES = {"title": 18, "label": 20, "big": 38, "small": 14}

_ROW_YS = (32, 100, 168)
_ROW_HEIGHT = 64
_BAR_Y_OFFSET = 50
_BAR_HEIGHT = 8
_SIDE_PAD = 12


def pct_color(pct: Optional[float]) -> str:
    if pct is None:
        return SUBTEXT
    if pct < 60:
        return OK
    if pct < 80:
        return WARN
    if pct < 90:
        return HIGH
    return CRIT


def _tokps_color(v: Optional[float]) -> str:
    if v is None:
        return SUBTEXT
    if v < 20:
        return CRIT
    if v < 40:
        return HIGH
    if v < 60:
        return WARN
    return OK


@lru_cache(maxsize=1)
def load_fonts() -> dict[str, ImageFont.ImageFont]:
    for path in _FONT_CANDIDATES:
        try:
            return {key: ImageFont.truetype(path, size) for key, size in _FONT_SIZES.items()}
        except OSError:
            continue
    return {key: ImageFont.load_default(size=size) for key, size in _FONT_SIZES.items()}


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pct_text(pct: Optional[float]) -> str:
    return f"{int(round(pct))}%" if pct is not None else "—"


def _new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw, dict]:
    img = Image.new("RGB", (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(img)
    return img, draw, load_fonts()


def _right_align(draw: ImageDraw.ImageDraw, text: str, right: int, y: int, font, fill: str) -> None:
    w = int(draw.textlength(text, font=font))
    draw.text((right - w, y), text, font=font, fill=fill)


def _draw_top_bar(draw: ImageDraw.ImageDraw, fonts: dict, title: str, page_idx: int, total: int = 4) -> None:
    draw.text((8, 3), title, font=fonts["title"], fill=TEXT)
    _right_align(draw, f"{page_idx}/{total}", SIZE - 8, 6, fonts["small"], SUBTEXT)


def _draw_row(
    draw: ImageDraw.ImageDraw,
    fonts: dict,
    y: int,
    label: str,
    value_text: str,
    value_color: str,
    pct: Optional[float],
    show_bar: bool = True,
    value_font_key: str = "big",
) -> None:
    draw.rectangle((4, y, SIZE - 4, y + _ROW_HEIGHT), fill=CARD)
    draw.text((_SIDE_PAD, y + 8), label, font=fonts["label"], fill=SUBTEXT)
    value_font = fonts[value_font_key]
    value_y = y + 6 if value_font_key == "big" else y + 12
    _right_align(draw, value_text, SIZE - _SIDE_PAD, value_y, value_font, value_color)

    if not show_bar or pct is None:
        return

    bar_left = _SIDE_PAD
    bar_right = SIZE - _SIDE_PAD
    bar_top = y + _BAR_Y_OFFSET
    bar_bottom = bar_top + _BAR_HEIGHT
    draw.rectangle((bar_left, bar_top, bar_right, bar_bottom), fill=BAR_BG)
    inner_w = bar_right - bar_left
    fill_w = max(0, min(inner_w, int(inner_w * pct / 100)))
    if fill_w > 0:
        draw.rectangle(
            (bar_left, bar_top, bar_left + fill_w, bar_bottom), fill=pct_color(pct)
        )


def _render_pct_page(title: str, page_idx: int, rows: list[tuple[str, Optional[float]]]) -> Image.Image:
    img, draw, fonts = _new_canvas()
    _draw_top_bar(draw, fonts, title, page_idx)
    for y, (label, pct) in zip(_ROW_YS, rows):
        _draw_row(
            draw,
            fonts,
            y,
            label,
            _pct_text(pct),
            pct_color(pct),
            pct,
            show_bar=pct is not None,
        )
    return img


def render_system(cpu: Optional[float], mem: Optional[float], disk: Optional[float]) -> Image.Image:
    return _render_pct_page("SYSTEM", 1, [("CPU", cpu), ("MEM", mem), ("DISK", disk)])


def render_claude(
    session: Optional[float], weekly: Optional[float], sonnet: Optional[float]
) -> Image.Image:
    return _render_pct_page(
        "CLAUDE", 2, [("SESSION", session), ("WEEKLY", weekly), ("SONNET", sonnet)]
    )


def render_other(
    codex: Optional[float], copilot: Optional[float], zhipu: Optional[float]
) -> Image.Image:
    return _render_pct_page(
        "OTHER", 3, [("CODEX", codex), ("COPILOT", copilot), ("ZHIPU", zhipu)]
    )


def render_local_llm(
    model: Optional[str],
    vram_pct: Optional[float],
    tok_per_sec: Optional[float],
) -> Image.Image:
    img, draw, fonts = _new_canvas()
    _draw_top_bar(draw, fonts, "LOCAL LLM", 4)

    model_text = model if model else "—"
    if len(model_text) > 14:
        model_text = model_text[:13] + "…"
    _draw_row(
        draw,
        fonts,
        _ROW_YS[0],
        "MODEL",
        model_text,
        TEXT,
        None,
        show_bar=False,
        value_font_key="label",
    )

    _draw_row(
        draw,
        fonts,
        _ROW_YS[1],
        "VRAM",
        _pct_text(vram_pct),
        pct_color(vram_pct),
        vram_pct,
        show_bar=vram_pct is not None,
    )

    tok_text = f"{tok_per_sec:.1f}" if tok_per_sec is not None else "—"
    _draw_row(
        draw,
        fonts,
        _ROW_YS[2],
        "TOK/S",
        tok_text,
        _tokps_color(tok_per_sec),
        None,
        show_bar=False,
    )
    return img
