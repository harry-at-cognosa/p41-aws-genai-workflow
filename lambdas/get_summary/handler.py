"""
get_summary Lambda — GET /summaries/{id}.

Returns the current state of a summary job, and (when DONE) the summary
markdown body inline. Bodies are capped at ~100 KB by the summarize step
so inlining is safe and avoids a second presigned-URL round trip.

Response shape (JSON):
    {
      "summary_id": "...",
      "status": "PENDING" | "PROCESSING" | "DONE" | "FAILED",
      "summary": "# Summary…",     # only when DONE
      "model_id": "...",            # only when DONE
      "input_tokens": 389,           # only when DONE
      "output_tokens": 230,          # only when DONE
      "error_message": "..."         # only when FAILED
    }
"""

from __future__ import annotations

import json

import boto3
from botocore.exceptions import ClientError

from shared import ddb, s3util
from shared.logging import get_logger

log = get_logger("get_summary")

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(204, {})

    path_params = event.get("pathParameters") or {}
    summary_id = path_params.get("id", "").strip()
    if not summary_id:
        return _response(400, {"error": "missing summary id"})

    item = ddb.get_summary(summary_id=summary_id)
    if item is None:
        return _response(404, {"error": "summary not found", "summary_id": summary_id})

    status = item.get("status")
    payload: dict = {"summary_id": summary_id, "status": status}

    if status == ddb.STATUS_DONE:
        summary_text = _read_summary_body(item.get("summary_s3_key"))
        if summary_text is None:
            log.error(
                "summary marked DONE but body missing",
                extra={"summary_id": summary_id, "key": item.get("summary_s3_key")},
            )
            return _response(500, {"error": "summary body missing", "summary_id": summary_id})
        payload.update(
            {
                "summary": summary_text,
                "model_id": item.get("model_id"),
                "input_tokens": int(item.get("input_tokens", 0)),
                "output_tokens": int(item.get("output_tokens", 0)),
            }
        )
    elif status == ddb.STATUS_FAILED:
        payload["error_message"] = item.get("error_message", "unknown error")

    return _response(200, payload)


def _read_summary_body(key: str | None) -> str | None:
    if not key:
        return None
    try:
        obj = boto3.client("s3").get_object(Bucket=s3util.bucket_name(), Key=key)
        return obj["Body"].read().decode("utf-8")
    except ClientError:
        return None


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": json.dumps(body),
    }
