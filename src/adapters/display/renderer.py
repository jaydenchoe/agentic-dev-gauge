"""Pillow-based renderer for GeekMagic SmallTV Ultra (240x240) dashboard frames.

V4 — Vertical Columns + Clock page.

Carousel (5 pages):
    1. CLOCK       — big HH:MM + seconds + date + BUDGET strip
    2. SYSTEM      — CPU / MEM / DISK   as segmented vertical columns
    3. CLAUDE      — SESSION / WEEKLY / SONNET
    4. OTHER       — CODEX / COPILOT / ZHIPU
    5. LOCAL LLM   — MODEL / VRAM / TOK/S

Every non-clock page shows a live HH:MM clock in the top bar.
"""

from __future__ import annotations

import io
from datetime import datetime
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

SIZE = 240

# ─── palette ──────────────────────────────────────────────────
BG         = "#0B0B0D"
CARD       = "#141418"
CARD_SEG   = "#1F1F22"         # inactive column segment
BORDER_DIM = "#1A1A1D"
TEXT       = "#E5E5E5"
TEXT_SUB   = "#9CA3AF"
TEXT_DIM   = "#737373"
TEXT_MUTED = "#525252"
ACCENT     = "#10B981"         # clock colon, "ok" hue

OK   = "#10B981"
WARN = "#F59E0B"
HIGH = "#F97316"
CRIT = "#EF4444"

# ─── layout constants ────────────────────────────────────────
TOP_BAR_H = 22
BOTTOM_DOTS_H = 4
COL_GAP = 6
COL_PAD_X = 10
COL_SEGMENTS = 14
SEG_GAP = 2
PAGE_COUNT = 5

# ─── fonts ───────────────────────────────────────────────────
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
_MONO_CANDIDATES = (
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
)

_FONT_SIZES = {
    "clock_big":  72,  # HH and MM on clock page
    "clock_sec":  24,  # seconds on clock page
    "clock_top":  18,  # HH:MM in top bar
    "date":       11,
    "page_label": 11,
    "col_value":  22,
    "col_value_text": 13,   # when value is a string (e.g. model name)
    "col_label":  10,
    "budget_label": 10,
    "budget_pct":  11,
    "section":    10,
    "counter":     9,
}


@lru_cache(maxsize=1)
def load_fonts() -> dict[str, ImageFont.ImageFont]:
    sans_path = next((p for p in _FONT_CANDIDATES if _try_open(p)), None)
    mono_path = next((p for p in _MONO_CANDIDATES if _try_open(p)), None)
    out: dict[str, ImageFont.ImageFont] = {}
    for key, size in _FONT_SIZES.items():
        path = mono_path if key.startswith("clock") or key in ("counter", "date") else sans_path
        try:
            out[key] = ImageFont.truetype(path or "", size) if path else ImageFont.load_default(size=size)
        except OSError:
            out[key] = ImageFont.load_default(size=size)
    return out


def _try_open(path: str) -> bool:
    try:
        ImageFont.truetype(path, 12)
        return True
    except OSError:
        return False


# ─── color helpers ───────────────────────────────────────────
def pct_color(pct: Optional[float]) -> str:
    if pct is None:
        return TEXT_SUB
    if pct < 60:
        return OK
    if pct < 80:
        return WARN
    if pct < 90:
        return HIGH
    return CRIT


def tps_color(v: Optional[float]) -> str:
    if v is None:
        return TEXT_SUB
    if v < 20:
        return CRIT
    if v < 40:
        return HIGH
    if v < 60:
        return WARN
    return OK


# ─── drawing primitives ──────────────────────────────────────
def _new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw, dict]:
    img = Image.new("RGB", (SIZE, SIZE), BG)
    return img, ImageDraw.Draw(img), load_fonts()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _draw_text_centered(draw, text, cx, y, font, fill):
    w = _text_w(draw, text, font)
    draw.text((cx - w // 2, y), text, font=font, fill=fill)


def _draw_text_right(draw, text, right, y, font, fill):
    draw.text((right - _text_w(draw, text, font), y), text, font=font, fill=fill)


def _draw_hline(draw, y, color=BORDER_DIM):
    draw.line((0, y, SIZE, y), fill=color)


def _draw_progress_dots(draw, active_idx: int) -> None:
    # 5 dots at the very bottom of the screen
    y = SIZE - 3
    pad_x = 6
    gap = 2
    total_w = SIZE - pad_x * 2
    seg_w = (total_w - gap * (PAGE_COUNT - 1)) / PAGE_COUNT
    for i in range(PAGE_COUNT):
        x0 = pad_x + i * (seg_w + gap)
        color = TEXT if i == active_idx else "#1F1F1F"
        draw.rectangle((x0, y, x0 + seg_w, y + 2), fill=color)


def _draw_top_bar(draw, fonts, title: str, page_idx_1based: int) -> None:
    """HH:MM (big) · TITLE (center) · NN/05 (right)."""
    now = datetime.now()
    clock = now.strftime("%H:%M")

    # left: clock
    draw.text((8, 3), clock, font=fonts["clock_top"], fill=TEXT)
    # color the colon green
    # draw HH in TEXT, colon in ACCENT, MM in TEXT (approximate width)
    # simpler: overlay a green colon exactly where the existing ':' is
    hh = clock[:2]
    hh_w = _text_w(draw, hh, fonts["clock_top"])
    draw.text((8 + hh_w, 3), ":", font=fonts["clock_top"], fill=ACCENT)

    # center: title
    _draw_text_centered(draw, title, SIZE // 2, 6, fonts["page_label"], TEXT_SUB)

    # right: page counter
    _draw_text_right(draw, f"{page_idx_1based:02d}/{PAGE_COUNT:02d}",
                     SIZE - 8, 7, fonts["counter"], TEXT_MUTED)

    _draw_hline(draw, TOP_BAR_H - 1)


# ─── columns page (SYSTEM / CLAUDE / OTHER / LOCAL) ──────────
def _draw_column(
    draw: ImageDraw.ImageDraw,
    fonts: dict,
    x: int, y: int, w: int, h: int,
    label: str,
    value_text: str,
    value_color: str,
    pct: Optional[float],
    value_is_text: bool = False,
) -> None:
    # card background
    draw.rectangle((x, y, x + w, y + h), fill=CARD)

    pad_top = 8
    pad_bot = 6
    pad_x = 4

    # value (top, centered)
    font_key = "col_value_text" if value_is_text else "col_value"
    vw = _text_w(draw, value_text, fonts[font_key])
    value_y = y + pad_top
    draw.text((x + (w - vw) // 2, value_y), value_text, font=fonts[font_key], fill=value_color)

    # bottom label
    lw = _text_w(draw, label, fonts["col_label"])
    label_y = y + h - pad_bot - 10
    draw.text((x + (w - lw) // 2, label_y), label, font=fonts["col_label"], fill=TEXT_SUB)

    # segmented column between value & label
    col_top = value_y + (24 if not value_is_text else 18)
    col_bot = label_y - 4
    col_h = col_bot - col_top
    if col_h <= 0:
        return

    segs = COL_SEGMENTS
    seg_h = (col_h - SEG_GAP * (segs - 1)) / segs
    if seg_h < 1:
        return

    col_w = w - pad_x * 2
    col_x = x + pad_x

    # how many active? — use pct if given, else "full" for text values
    if pct is None:
        if value_is_text:
            active = segs
            seg_color = TEXT_DIM
        else:
            active = 0
            seg_color = TEXT_SUB
    else:
        active = round((pct / 100.0) * segs)
        seg_color = pct_color(pct)

    # draw bottom-up
    for i in range(segs):
        # i=0 is bottom
        seg_y1 = col_bot - i * (seg_h + SEG_GAP)
        seg_y0 = seg_y1 - seg_h
        if i < active:
            fill = seg_color
        else:
            fill = CARD_SEG
        draw.rectangle((col_x, seg_y0, col_x + col_w, seg_y1), fill=fill)


def _render_columns_page(
    title: str,
    page_idx_1based: int,
    columns: list[tuple[str, str, str, Optional[float], bool]],
    # (label, value_text, value_color, pct_or_None, value_is_text)
    anim_pct: float = 1.0,  # 0.0→1.0 fill progress for animation frames
) -> Image.Image:
    img, draw, fonts = _new_canvas()
    _draw_top_bar(draw, fonts, title, page_idx_1based)

    top = TOP_BAR_H + 8
    bot = SIZE - BOTTOM_DOTS_H - 6
    area_h = bot - top
    area_left = COL_PAD_X
    area_right = SIZE - COL_PAD_X
    area_w = area_right - area_left
    col_w = (area_w - COL_GAP * 2) / 3

    for i, (label, value_text, value_color, pct, is_text) in enumerate(columns):
        x = int(area_left + i * (col_w + COL_GAP))
        scaled_pct = (pct * anim_pct) if (pct is not None and anim_pct < 1.0) else pct
        _draw_column(draw, fonts, x, top, int(col_w), area_h,
                     label, value_text, value_color, scaled_pct, value_is_text=is_text)

    _draw_progress_dots(draw, page_idx_1based - 1)
    return img


def _pct_text(pct: Optional[float]) -> str:
    return f"{int(round(pct))}%" if pct is not None else "—"


# ─── public render_* functions ───────────────────────────────
def render_clock(
    session_pct: Optional[float] = None,
    weekly_pct: Optional[float] = None,
    disk_pct: Optional[float] = None,
) -> Image.Image:
    """Hero clock page with a 3-row BUDGET strip."""
    img, draw, fonts = _new_canvas()
    now = datetime.now()

    # top micro-bar: DATE · page counter
    date_str = now.strftime("%a %b %-d").upper() if hasattr(now, "strftime") else ""
    try:
        date_str = now.strftime("%a %b %-d").upper()
    except ValueError:
        # Windows — no %-d
        date_str = now.strftime("%a %b %#d").upper()
    draw.text((10, 5), date_str, font=fonts["date"], fill=TEXT_SUB)
    _draw_text_right(draw, f"01/{PAGE_COUNT:02d}", SIZE - 8, 7, fonts["counter"], TEXT_MUTED)
    _draw_hline(draw, TOP_BAR_H - 1)

    # Big clock — HH : MM SS
    hh = now.strftime("%H")
    mm = now.strftime("%M")
    ss = now.strftime("%S")
    f_big = fonts["clock_big"]
    f_sec = fonts["clock_sec"]

    hh_w = _text_w(draw, hh, f_big)
    colon_w = _text_w(draw, ":", f_big)
    mm_w = _text_w(draw, mm, f_big)
    spacer = 4  # gap between MM and SS
    clock_y = TOP_BAR_H + 14
    # Center only HH:MM; SS floats to the right independently
    hhmm_w = hh_w + colon_w + mm_w
    x = (SIZE - hhmm_w) // 2

    draw.text((x, clock_y), hh, font=f_big, fill=TEXT)
    x += hh_w
    colon_color = ACCENT if (now.second % 2 == 0) else "#0E3A2A"
    draw.text((x, clock_y), ":", font=f_big, fill=colon_color)
    x += colon_w
    draw.text((x, clock_y), mm, font=f_big, fill=TEXT)
    # seconds sit below and to the right of MM
    draw.text((x + mm_w + spacer, clock_y + 40), ss, font=f_sec, fill=TEXT_MUTED)

    # BUDGET strip — 3 mini rows
    strip_y = clock_y + 80
    draw.text((10, strip_y), "BUDGET", font=fonts["section"], fill=TEXT_MUTED)
    row_y = strip_y + 14
    for label, pct in (("CLAUDE", session_pct), ("WEEKLY", weekly_pct), ("DISK", disk_pct)):
        _draw_budget_row(draw, fonts, row_y, label, pct)
        row_y += 14

    _draw_progress_dots(draw, 0)
    return img


def _draw_budget_row(draw, fonts, y: int, label: str, pct: Optional[float]) -> None:
    # LABEL (52px) · bar (flex) · NN%
    left = 10
    right = SIZE - 10
    label_w = 46
    pct_w = 28
    gap = 6
    bar_left = left + label_w + gap
    bar_right = right - pct_w - gap

    draw.text((left, y), label, font=fonts["budget_label"], fill=TEXT_SUB)

    # bar track
    bar_y0 = y + 4
    bar_y1 = y + 8
    draw.rectangle((bar_left, bar_y0, bar_right, bar_y1), fill=CARD)

    if pct is not None:
        col = pct_color(pct)
        width = max(1, int((bar_right - bar_left) * pct / 100))
        draw.rectangle((bar_left, bar_y0, bar_left + width, bar_y1), fill=col)
        pct_text = f"{int(round(pct))}%"
    else:
        col = TEXT_SUB
        pct_text = "—"

    _draw_text_right(draw, pct_text, right, y, fonts["budget_pct"], col)


_ANIM_FRAMES = 12
_ANIM_FRAME_MS = 80


def _ease_out(t: float) -> float:
    """Quadratic ease-out: fast start, slow finish."""
    return 1.0 - (1.0 - t) ** 2


def render_system(cpu: Optional[float], mem: Optional[float], disk: Optional[float]) -> Image.Image:
    cols = [
        ("CPU",  _pct_text(cpu),  pct_color(cpu),  cpu,  False),
        ("MEM",  _pct_text(mem),  pct_color(mem),  mem,  False),
        ("DISK", _pct_text(disk), pct_color(disk), disk, False),
    ]
    return _render_columns_page("SYSTEM", 2, cols)


def render_system_animated(cpu: Optional[float], mem: Optional[float], disk: Optional[float]) -> list[Image.Image]:
    cols = [
        ("CPU",  _pct_text(cpu),  pct_color(cpu),  cpu,  False),
        ("MEM",  _pct_text(mem),  pct_color(mem),  mem,  False),
        ("DISK", _pct_text(disk), pct_color(disk), disk, False),
    ]
    return [_render_columns_page("SYSTEM", 2, cols, _ease_out((i + 1) / _ANIM_FRAMES))
            for i in range(_ANIM_FRAMES)]


def render_claude(session: Optional[float], weekly: Optional[float], sonnet: Optional[float]) -> Image.Image:
    cols = [
        ("SESSION", _pct_text(session), pct_color(session), session, False),
        ("WEEKLY",  _pct_text(weekly),  pct_color(weekly),  weekly,  False),
        ("SONNET",  _pct_text(sonnet),  pct_color(sonnet),  sonnet,  False),
    ]
    return _render_columns_page("CLAUDE", 3, cols)


def render_claude_animated(session: Optional[float], weekly: Optional[float], sonnet: Optional[float]) -> list[Image.Image]:
    cols = [
        ("SESSION", _pct_text(session), pct_color(session), session, False),
        ("WEEKLY",  _pct_text(weekly),  pct_color(weekly),  weekly,  False),
        ("SONNET",  _pct_text(sonnet),  pct_color(sonnet),  sonnet,  False),
    ]
    return [_render_columns_page("CLAUDE", 3, cols, _ease_out((i + 1) / _ANIM_FRAMES))
            for i in range(_ANIM_FRAMES)]


def render_other(codex: Optional[float], copilot: Optional[float], zhipu: Optional[float]) -> Image.Image:
    cols = [
        ("CODEX",   _pct_text(codex),   pct_color(codex),   codex,   False),
        ("COPILOT", _pct_text(copilot), pct_color(copilot), copilot, False),
        ("ZHIPU",   _pct_text(zhipu),   pct_color(zhipu),   zhipu,   False),
    ]
    return _render_columns_page("OTHER", 4, cols)


def render_other_animated(codex: Optional[float], copilot: Optional[float], zhipu: Optional[float]) -> list[Image.Image]:
    cols = [
        ("CODEX",   _pct_text(codex),   pct_color(codex),   codex,   False),
        ("COPILOT", _pct_text(copilot), pct_color(copilot), copilot, False),
        ("ZHIPU",   _pct_text(zhipu),   pct_color(zhipu),   zhipu,   False),
    ]
    return [_render_columns_page("OTHER", 4, cols, _ease_out((i + 1) / _ANIM_FRAMES))
            for i in range(_ANIM_FRAMES)]


def render_local_llm(
    model: Optional[str],
    vram_pct: Optional[float],
    tok_per_sec: Optional[float],
) -> Image.Image:
    model_text = (model or "—")
    if len(model_text) > 10:
        model_text = model_text[:9] + "…"
    tps_text = f"{tok_per_sec:.1f}" if tok_per_sec is not None else "—"
    cols = [
        ("MODEL", model_text,            TEXT,                 None,     True),
        ("VRAM",  _pct_text(vram_pct),   pct_color(vram_pct),  vram_pct, False),
        ("TOK/S", tps_text,              tps_color(tok_per_sec), None,   True),
    ]
    return _render_columns_page("LOCAL LLM", 5, cols)


def render_local_llm_animated(
    model: Optional[str],
    vram_pct: Optional[float],
    tok_per_sec: Optional[float],
) -> list[Image.Image]:
    model_text = (model or "—")
    if len(model_text) > 10:
        model_text = model_text[:9] + "…"
    tps_text = f"{tok_per_sec:.1f}" if tok_per_sec is not None else "—"
    cols = [
        ("MODEL", model_text,            TEXT,                 None,     True),
        ("VRAM",  _pct_text(vram_pct),   pct_color(vram_pct),  vram_pct, False),
        ("TOK/S", tps_text,              tps_color(tok_per_sec), None,   True),
    ]
    return [_render_columns_page("LOCAL LLM", 5, cols, _ease_out((i + 1) / _ANIM_FRAMES))
            for i in range(_ANIM_FRAMES)]


def render_clock_animated(
    session_pct: Optional[float] = None,
    weekly_pct: Optional[float] = None,
    disk_pct: Optional[float] = None,
) -> list[Image.Image]:
    """Clock page: colons blink across 12 frames (6 on / 6 off)."""
    return [render_clock(session_pct, weekly_pct, disk_pct) for _ in range(_ANIM_FRAMES)]


# ─── bytes helpers ───────────────────────────────────────────
def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def gif_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="GIF")
    return buf.getvalue()


def animated_gif_bytes(frames: list[Image.Image], frame_ms: int = _ANIM_FRAME_MS) -> bytes:
    buf = io.BytesIO()
    converted = [f.convert("P", palette=Image.ADAPTIVE, dither=0) for f in frames]
    converted[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=converted[1:],
        duration=frame_ms,
        loop=0,
        optimize=False,
    )
    return buf.getvalue()
