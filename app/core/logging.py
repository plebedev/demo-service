"""Logging configuration helpers for the backend service."""

import json
import logging
from logging.config import dictConfig
from typing import Any


def configure_logging(log_level: str) -> None:
    """Configure the root logger for application processes."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                }
            },
            "root": {
                "handlers": ["console"],
                "level": log_level,
            },
        }
    )


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a compact JSON application event in the normal log stream."""
    logger.log(level, json.dumps({"event": event, **fields}, sort_keys=True))
