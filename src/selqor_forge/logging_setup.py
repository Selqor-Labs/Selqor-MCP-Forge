# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Logging initialization with structured logging support."""

from __future__ import annotations

import logging
import os
import sys
import threading

import structlog

_init_lock = threading.Lock()
_initialized = False


class ProductionFormatter(logging.Formatter):
    """JSON formatter for production logging (compatible with log aggregators)."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON for structured logging."""
        import json

        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        return json.dumps(log_data)


def init() -> None:
    """Initialize logging with structlog and appropriate formatters."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    # Get log level from environment
    level_name = (
        os.environ.get("SELQOR_FORGE_LOG", os.environ.get("LOG_LEVEL", "INFO"))
        .upper()
        .strip()
    )
    level = getattr(logging, level_name, logging.INFO)

    # Determine if running in production
    is_production = os.environ.get("ENVIRONMENT", "development").lower() == "production"

    # Configure standard logging
    handler = logging.StreamHandler(sys.stdout)

    if is_production:
        # Production: Use JSON formatter for log aggregators
        formatter = ProductionFormatter()
    else:
        # Development: Use human-readable format
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    logging.basicConfig(
        level=level,
        handlers=[handler],
        format="%(message)s",
    )

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
    ]

    if is_production:
        # Production: JSON output for log aggregation
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Development: Pretty console output
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger.debug(
        "logging initialized",
        level=level_name,
        environment=os.environ.get("ENVIRONMENT", "development"),
        json_output=is_production,
    )
