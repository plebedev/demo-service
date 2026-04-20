"""Logging configuration helpers for the backend service."""

from logging.config import dictConfig


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
