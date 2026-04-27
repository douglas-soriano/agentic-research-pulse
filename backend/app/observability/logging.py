"""
Configure structlog as the application logging backend.

Call configure_logging() once at process startup (main.py, celery_worker.py).
All modules then use structlog.get_logger(__name__) to get a bound logger.
Context variables (job_id, agent_name, step) set via bind_contextvars() are
automatically merged into every log entry.
"""
import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    # Processors shared between structlog native calls and foreign stdlib calls.
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # Configure structlog to route through stdlib, which then formats as JSON.
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # stdlib handler with structlog JSON formatter (handles both native structlog
    # calls and third-party logging that goes through stdlib).
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
