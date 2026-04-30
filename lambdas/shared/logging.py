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


def get_logger(name: str = "summarizer") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    logger.propagate = False
    return logger
