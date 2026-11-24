from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[3] / "data" / "logs"


def setup_logging(level: str | None = None) -> None:
    lvl = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    if getattr(root, "_xiyou_logging_ready", False):
        return
    root.setLevel(lvl)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_DIR / "api.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass
    root._xiyou_logging_ready = True  # type: ignore[attr-defined]
