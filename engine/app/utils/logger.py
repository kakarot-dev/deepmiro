"""Logging setup. One rotating file handler + one stderr handler per logger.

Public API:
  - `setup_logger(name)` — call once during app init to configure handlers.
  - `get_logger(name)` — convenience accessor; auto-initializes on first use.

Linux-only — the Windows UTF-8 stdout shim from earlier MiroFish versions
was removed in v1.7.0.
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs',
)


def setup_logger(name: str = 'mirofish', level: int = logging.DEBUG) -> logging.Logger:
    """Configure a logger with a rotating file handler + a stderr handler.

    Safe to call multiple times for the same name — handlers are only
    attached on the first call.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger

    os.makedirs(LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, datetime.now().strftime('%Y-%m-%d') + '.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    ))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def get_logger(name: str = 'mirofish') -> logging.Logger:
    """Get a logger, auto-initializing it on first access."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
