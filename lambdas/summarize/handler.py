"""
summarize Lambda — triggered by S3 ObjectCreated:* on uploads/*.

Thin orchestrator: parses the S3 event, walks the document through the
PROCESSING → DONE | FAILED state machine, and delegates the actual model
call to the pure summarize_text() function in shared/bedrock.py.

Failures are recorded in DDB *and* re-raised — re-raising lets Lambda's
async destination route the bad event to the SQS DLQ, which we monitor
with a CloudWatch alarm.
"""

import os
import urllib.parse

from shared import ddb, s3util
from shared.bedrock import summarize_text
from shared.errors import InvalidDocumentError, ModelInvocationError, SummarizerError
from shared.logging import get_logger

log = get_logger("summarize")

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)


def handler(event, context):
    # An S3 PutObject event can carry multiple records when the upload is
    # part of a batch; iterate even though our presigned-URL flow always
    # uploads one object at a time.
    for record in event.get("Records", []):
        _process_record(record)


def _process_record(record: dict) -> None:
    s3_info = record.get("s3", {})
    bucket = s3_info.get("bucket", {}).get("name")
    raw_key = s3_info.get("object", {}).get("key", "")
    # S3 event keys are URL-encoded (spaces become +, etc.). Decode first.
    key = urllib.parse.unquote_plus(raw_key)

    if not bucket or not key:
        log.error("missing bucket or key in event record", extra={"record": record})
        return

    summary_id = s3util.parse_summary_id_from_key(key)
    log.info("summarize start", extra={"summary_id": summary_id, "key": key})

    try:
        ddb.mark_processing(summary_id=summary_id)
        text = s3util.read_text(key=key)
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
        # Unknown failure — record it and re-raise so the DLQ catches it.
        log.exception("summarize failed (unexpected)", extra={"summary_id": summary_id})
        ddb.mark_failed(summary_id=summary_id, error_message=f"unexpected: {e!r}")
        raise
