"""
request_upload Lambda — POST /uploads.

Generates a presigned S3 PUT URL the caller uses to upload bytes directly
to S3 (avoids API Gateway's 10 MB payload limit and Lambda's similar one).
Also seeds a PENDING row in the Summaries table so polling works as soon
as the caller has the summary_id.

Request body (JSON):
    { "filename": "my_document.pdf" }   — required to pick the right
                                          extractor (txt/md/pdf/docx)

Response (JSON):
    { "summary_id": "...",
      "upload_url": "...",
      "expires_in_seconds": 300 }
"""

from __future__ import annotations

import json
import os
import uuid

import boto3
from botocore.config import Config

from shared import ddb, s3util
from shared.extractors import ACCEPTED_EXTENSIONS, extension_of
from shared.logging import get_logger

log = get_logger("request_upload")

PRESIGNED_URL_EXPIRY_SECONDS = 300  # 5 minutes
MAX_FILENAME_LEN = 255

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(204, {})

    filename = _parse_filename(event)
    ext = extension_of(filename) or "txt"
    if ext not in ACCEPTED_EXTENSIONS:
        return _response(
            400,
            {
                "error": f"unsupported file type {ext!r}",
                "accepted": list(ACCEPTED_EXTENSIONS),
            },
        )

    summary_id = str(uuid.uuid4())
    # Preserve the original extension in the S3 key. The summarize Lambda
    # parses it back out to pick the right extractor.
    key = f"{s3util.UPLOADS_PREFIX}{summary_id}.{ext}"

    bucket = s3util.bucket_name()
    s3 = boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    ddb.put_pending(summary_id=summary_id, source_filename=filename)

    log.info(
        "issued upload url",
        extra={"summary_id": summary_id, "source_filename": filename, "key": key},
    )
    return _response(
        201,
        {
            "summary_id": summary_id,
            "upload_url": upload_url,
            "expires_in_seconds": PRESIGNED_URL_EXPIRY_SECONDS,
        },
    )


def _parse_filename(event: dict) -> str:
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {}
    filename = body.get("filename") or "untitled.txt"
    if not isinstance(filename, str):
        filename = "untitled.txt"
    return filename[:MAX_FILENAME_LEN]


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": json.dumps(body),
    }
