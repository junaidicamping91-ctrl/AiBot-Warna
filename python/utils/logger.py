"""Logger sederhana untuk pipeline vision -> serial -> audio."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logger(level: str = "INFO", log_file: str | None = None) -> logging.Logger:
    global _CONFIGURED
    log = logging.getLogger("aimbot")
    if _CONFIGURED:
        return log
    log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    log.addHandler(stream)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)
    log.propagate = False
    _CONFIGURED = True
    return log
