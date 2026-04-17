"""Render the 4 carousel pages with sample data for visual inspection.

Usage:
    .venv/bin/python _workspace/geekmagic/preview.py

Outputs:
    _workspace/geekmagic/out/page_1.png  (SYSTEM)
    _workspace/geekmagic/out/page_2.png  (CLAUDE)
    _workspace/geekmagic/out/page_3.png  (OTHER)
    _workspace/geekmagic/out/page_4.png  (LOCAL LLM)
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.adapters.display.renderer import (
    render_claude,
    render_local_llm,
    render_other,
    render_system,
)


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = [
        (1, render_system(cpu=47, mem=34, disk=90)),
        (2, render_claude(session=42, weekly=16, sonnet=3)),
        (3, render_other(codex=1, copilot=21, zhipu=0)),
        (4, render_local_llm(model="qwen3:32b", vram_pct=78, tok_per_sec=54.2)),
    ]
    for idx, img in pages:
        path = out_dir / f"page_{idx}.png"
        img.save(path, format="PNG")
        print(f"wrote {path.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
