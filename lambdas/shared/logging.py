"""
Structured JSON logger for Lambda. CloudWatch parses JSON automatically and
makes the fields filterable via Logs Insights, which is much nicer than
free-form prints when chasing failures.
"""

import json
import logging
import os
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # `extra={...}` keys land directly on the record; pull anything custom.
        for k, v in record.__dict__.items():
            if k not in _STD_KEYS and not k.startswith("_"):
                payload[k] = v
        return json.dumps(payload, default=str)


_STD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class _SafeAdapter(logging.LoggerAdapter):
    """
    LoggerAdapter that pre-renames any `extra={…}` key colliding with a
    LogRecord reserved attribute (e.g. `filename`, `module`, `name`) by
    prepending `x_`. Without this, calling `log.info(msg, extra={"filename":…})`
    raises `KeyError: "Attempt to overwrite 'filename' in LogRecord"` —
    which bit the request_upload Lambda in Phase 3.
    """

    def process(self, msg, kwargs):
        extra = kwargs.get("extra")
        if extra:
            renamed = {}
            for k, v in extra.items():
                renamed[("x_" + k) if k in _STD_KEYS else k] = v
            kwargs["extra"] = renamed
        return msg, kwargs


def get_logger(name: str = "summarizer") -> logging.LoggerAdapter:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
        logger.propagate = False
    return _SafeAdapter(logger, {})
