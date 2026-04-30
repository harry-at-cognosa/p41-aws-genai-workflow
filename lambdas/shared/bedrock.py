"""
Bedrock summarization core — THE V2.0 SEAM.

`summarize_text()` is intentionally pure: it takes a string and configuration,
calls Bedrock via boto3, and returns a `SummaryResult`. It knows nothing about
S3, DynamoDB, Lambda events, or HTTP. v2.0 (FastAPI/Postgres) will import this
function unchanged from a route handler.

Bedrock-hosted Claude accepts the same Anthropic Messages API shape we'd use
for direct Anthropic API calls (`anthropic_version`, `messages`, `max_tokens`,
`system`), so this code is also portable to a direct Anthropic client by
swapping the `bedrock-runtime` invoke for an `anthropic.Anthropic().messages.create`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .errors import ModelInvocationError
from .logging import get_logger
from .prompts import SYSTEM, render_user_message

log = get_logger(__name__)

# Approximate input budget. Claude's context window is far larger, but we cap
# at ~100 KB of UTF-8 to keep latency and per-call cost bounded for a PoC.
MAX_INPUT_CHARS = 100_000
DEFAULT_MAX_OUTPUT_TOKENS = 1024
ANTHROPIC_VERSION = "bedrock-2023-05-31"

# Errors that indicate transient capacity / network issues; worth retrying.
_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "ModelStreamErrorException",
    "InternalServerException",
}


@dataclass(frozen=True)
class SummaryResult:
    text: str
    model_id: str
    input_tokens: int
    output_tokens: int


def _client():
    # botocore Config: short connect timeout, longer read timeout (model latency),
    # and a small built-in retry layer on top of our own retries below.
    cfg = Config(
        connect_timeout=5,
        read_timeout=55,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    region = os.environ.get("AWS_REGION", "us-west-2")
    return boto3.client("bedrock-runtime", region_name=region, config=cfg)


def summarize_text(
    document: str,
    *,
    model_id: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_retries: int = 3,
) -> SummaryResult:
    """
    Summarize a document. Pure function w.r.t. the rest of the system —
    no S3, no DDB, no Lambda event shapes.
    """
    if not document or not document.strip():
        # Treat empty/whitespace-only as a domain error rather than calling
        # the model on nothing. Caller should map this to a FAILED status.
        raise ModelInvocationError("document is empty")

    truncated = document[:MAX_INPUT_CHARS]
    body = {
        "anthropic_version": ANTHROPIC_VERSION,
        "max_tokens": max_output_tokens,
        "system": SYSTEM,
        "messages": [
            {"role": "user", "content": render_user_message(truncated)},
        ],
    }

    client = _client()
    attempt = 0
    backoff = 1.0
    while True:
        attempt += 1
        try:
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                accept="application/json",
                contentType="application/json",
            )
            payload = json.loads(response["body"].read())
            return _parse_response(payload, model_id=model_id)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in _RETRYABLE_ERROR_CODES and attempt < max_retries:
                log.warning(
                    "bedrock retryable error",
                    extra={"code": code, "attempt": attempt, "backoff_s": backoff},
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            raise ModelInvocationError(f"bedrock InvokeModel failed: {code}") from e


def _parse_response(payload: dict, *, model_id: str) -> SummaryResult:
    # Anthropic Messages response shape: {content: [{type: "text", text: "..."}], usage: {input_tokens, output_tokens}}
    blocks = payload.get("content", [])
    text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    text = "".join(text_parts).strip()
    if not text:
        raise ModelInvocationError("bedrock returned no text content")
    usage = payload.get("usage", {})
    return SummaryResult(
        text=text,
        model_id=model_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )
