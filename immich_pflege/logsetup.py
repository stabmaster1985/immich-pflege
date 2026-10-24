"""Logging nach stdout und in eine Datei unter DATA_DIR."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup_logging(log_file: Path | None, level: int = logging.INFO, stdout: bool = True) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("immich_pflege")
    root.setLevel(level)
    formatter = logging.Formatter(FORMAT)
    if stdout:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except OSError as exc:
            root.warning("Logdatei %s nicht beschreibbar: %s", log_file, exc)
    _configured = True
