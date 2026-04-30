"""
Thin DynamoDB helpers for the Summaries table.

Schema lives here so v2.0's Postgres migration is a near-1:1 port: every
attribute is a flat scalar (no nested maps) and the status enum is shared.
"""

from __future__ import annotations

import os
import time
from typing import Any

import boto3

_TABLE_ENV = "SUMMARIES_TABLE"

# Mirrors the column set we'll create in Postgres for v2.0.
STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

# 30 days from creation — matches the bucket's uploads/ lifecycle rule.
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60


def _table():
    name = os.environ.get(_TABLE_ENV)
    if not name:
        raise RuntimeError(f"{_TABLE_ENV} env var is not set")
    return boto3.resource("dynamodb").Table(name)


def put_pending(
    *,
    summary_id: str,
    source_filename: str,
    created_at: int | None = None,
) -> None:
    """Create the initial row when a presigned upload URL is issued."""
    now = created_at or int(time.time())
    _table().put_item(
        Item={
            "summary_id": summary_id,
            "status": STATUS_PENDING,
            "created_at": now,
            "source_filename": source_filename,
            "expires_at": now + DEFAULT_TTL_SECONDS,
        }
    )


def mark_processing(*, summary_id: str) -> None:
    _table().update_item(
        Key={"summary_id": summary_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": STATUS_PROCESSING},
    )


def mark_done(
    *,
    summary_id: str,
    summary_s3_key: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    _table().update_item(
        Key={"summary_id": summary_id},
        UpdateExpression=(
            "SET #s = :s, summary_s3_key = :k, model_id = :m, "
            "input_tokens = :it, output_tokens = :ot, completed_at = :ts"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": STATUS_DONE,
            ":k": summary_s3_key,
            ":m": model_id,
            ":it": input_tokens,
            ":ot": output_tokens,
            ":ts": int(time.time()),
        },
    )


def mark_failed(*, summary_id: str, error_message: str) -> None:
    _table().update_item(
        Key={"summary_id": summary_id},
        UpdateExpression="SET #s = :s, error_message = :e, completed_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": STATUS_FAILED,
            ":e": error_message[:1024],  # cap to keep DDB rows small
            ":ts": int(time.time()),
        },
    )


def get_summary(*, summary_id: str) -> dict[str, Any] | None:
    resp = _table().get_item(Key={"summary_id": summary_id})
    return resp.get("Item")
