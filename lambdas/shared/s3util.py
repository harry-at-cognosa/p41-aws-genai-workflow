"""
Small S3 helpers used by the Lambda handlers. Wrapped here so v2.0 can swap
S3 for a local filesystem or Postgres-bytea backend by editing one file.
"""

from __future__ import annotations

import os

import boto3

from .errors import InvalidDocumentError

_BUCKET_ENV = "DOCUMENTS_BUCKET"
UPLOADS_PREFIX = "uploads/"
SUMMARIES_PREFIX = "summaries/"


def _client():
    return boto3.client("s3")


def bucket_name() -> str:
    name = os.environ.get(_BUCKET_ENV)
    if not name:
        raise RuntimeError(f"{_BUCKET_ENV} env var is not set")
    return name


def read_bytes(*, key: str) -> bytes:
    """Read raw bytes from an S3 object. No format assumptions."""
    obj = _client().get_object(Bucket=bucket_name(), Key=key)
    return obj["Body"].read()


def read_text(*, key: str) -> str:
    """Read a UTF-8 text object. Raises InvalidDocumentError on bad bytes.

    Kept for callers that already know they're dealing with text; the
    summarize Lambda uses read_bytes + extractors.extract_text now.
    """
    try:
        return read_bytes(key=key).decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidDocumentError(f"object {key} is not valid UTF-8 text") from e


def write_summary(*, summary_id: str, text: str) -> str:
    """Write the summary markdown to summaries/{id}.md and return the S3 key."""
    key = f"{SUMMARIES_PREFIX}{summary_id}.md"
    _client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    return key


def parse_summary_id_from_key(key: str) -> str:
    """uploads/{summary_id}.{ext} → summary_id."""
    if not key.startswith(UPLOADS_PREFIX):
        raise ValueError(f"unexpected key prefix: {key!r}")
    name = key[len(UPLOADS_PREFIX):]
    return name.rsplit(".", 1)[0] if "." in name else name
