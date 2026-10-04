"""Logging a consola y a archivo rotativo, con formato `[NIVEL] mensaje`."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import get_settings

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if getattr(root, "_bot_configured", False):
        return
    root.setLevel(settings.log_level.upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    root._bot_configured = True  # type: ignore[attr-defined]
