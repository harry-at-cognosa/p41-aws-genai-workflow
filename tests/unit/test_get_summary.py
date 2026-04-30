"""
get_summary handler tests: covers PENDING/PROCESSING/DONE/FAILED and 404.
"""

import json

import boto3

from get_summary import handler as gs
from shared import ddb


def _event(summary_id, method="GET"):
    return {"httpMethod": method, "pathParameters": {"id": summary_id}}


def test_returns_404_for_unknown_id(bucket, table):
    resp = gs.handler(_event("nope"), None)
    assert resp["statusCode"] == 404


def test_pending_returns_status_only(bucket, table):
    ddb.put_pending(summary_id="p1", source_filename="x.txt")
    resp = gs.handler(_event("p1"), None)
    body = json.loads(resp["body"])
    assert body["status"] == ddb.STATUS_PENDING
    assert "summary" not in body


def test_done_returns_summary_body_inline(bucket, table):
    # Seed a complete DONE row + the corresponding S3 object.
    ddb.put_pending(summary_id="d1", source_filename="x.txt")
    boto3.client("s3").put_object(
        Bucket=bucket, Key="summaries/d1.md", Body=b"# Summary\n\nbody"
    )
    ddb.mark_done(
        summary_id="d1",
        summary_s3_key="summaries/d1.md",
        model_id="us.anthropic.claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
    )

    resp = gs.handler(_event("d1"), None)
    body = json.loads(resp["body"])
    assert body["status"] == ddb.STATUS_DONE
    assert body["summary"] == "# Summary\n\nbody"
    assert body["model_id"] == "us.anthropic.claude-sonnet-4-6"
    assert body["input_tokens"] == 100
    assert body["output_tokens"] == 50


def test_failed_returns_error_message(bucket, table):
    ddb.put_pending(summary_id="f1", source_filename="x.txt")
    ddb.mark_failed(summary_id="f1", error_message="bedrock said no")

    resp = gs.handler(_event("f1"), None)
    body = json.loads(resp["body"])
    assert body["status"] == ddb.STATUS_FAILED
    assert body["error_message"] == "bedrock said no"
