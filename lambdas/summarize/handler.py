"""
summarize Lambda — triggered by S3 ObjectCreated:* on uploads/*.

Thin orchestrator: parses the S3 event, walks the document through the
PROCESSING → DONE | FAILED state machine, dispatches the bytes through
extractors.extract_text (which handles txt/md/pdf/docx), and delegates
the model call to the pure summarize_text() function in shared/bedrock.py.

Failures are recorded in DDB *and* re-raised — re-raising lets Lambda's
async destination route the bad event to the SQS DLQ, which we monitor
with a CloudWatch alarm.
"""

import os
import urllib.parse

from shared import ddb, s3util
from shared.bedrock import summarize_text
from shared.errors import InvalidDocumentError, ModelInvocationError, SummarizerError
from shared.extractors import extract_text
from shared.logging import get_logger

log = get_logger("summarize")

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)


def handler(event, context):
    for record in event.get("Records", []):
        _process_record(record)


def _process_record(record: dict) -> None:
    s3_info = record.get("s3", {})
    bucket = s3_info.get("bucket", {}).get("name")
    raw_key = s3_info.get("object", {}).get("key", "")
    key = urllib.parse.unquote_plus(raw_key)

    if not bucket or not key:
        log.error("missing bucket or key in event record", extra={"record": record})
        return

    summary_id = s3util.parse_summary_id_from_key(key)
    log.info("summarize start", extra={"summary_id": summary_id, "key": key})

    try:
        ddb.mark_processing(summary_id=summary_id)
        # Read raw bytes first; the extractor decides how to turn them into
        # text based on the key's extension (preserved from the user's
        # original filename by request_upload).
        raw = s3util.read_bytes(key=key)
        text = extract_text(filename=key, raw_bytes=raw)
        result = summarize_text(text, model_id=MODEL_ID)
        summary_key = s3util.write_summary(summary_id=summary_id, text=result.text)
        ddb.mark_done(
            summary_id=summary_id,
            summary_s3_key=summary_key,
            model_id=result.model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        log.info(
            "summarize done",
            extra={
                "summary_id": summary_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
    except (InvalidDocumentError, ModelInvocationError, SummarizerError) as e:
        log.error("summarize failed (domain)", extra={"summary_id": summary_id, "error": str(e)})
        ddb.mark_failed(summary_id=summary_id, error_message=str(e))
        raise
    except Exception as e:
        log.exception("summarize failed (unexpected)", extra={"summary_id": summary_id})
        ddb.mark_failed(summary_id=summary_id, error_message=f"unexpected: {e!r}")
        raise
