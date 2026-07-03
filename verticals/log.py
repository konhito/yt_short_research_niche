"""Structured file + console logging."""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from .config import LOGS_DIR

_logger = None


def get_logger() -> logging.Logger:
    """Get or create the pipeline logger with file + console handlers."""
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("pipeline")
    _logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on re-import.
    if _logger.handlers:
        return _logger

    # Console handler: INFO by default, DEBUG with --verbose.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("  %(message)s"))
    _logger.addHandler(console)

    # File handler is best effort. In locked-down environments, console logging
    # is still enough to keep the pipeline usable.
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOGS_DIR / f"pipeline_{datetime.now():%Y%m%d}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
        )
        _logger.addHandler(file_handler)
    except Exception:
        pass

    return _logger


def set_verbose(verbose: bool = True):
    """Switch console handler to DEBUG level."""
    logger = get_logger()
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.DEBUG if verbose else logging.INFO)


def log(msg: str):
    """Convenience wrapper: INFO level."""
    get_logger().info(msg)
