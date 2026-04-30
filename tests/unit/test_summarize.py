"""
summarize handler tests: walks an S3 event through PENDING → PROCESSING →
DONE, plus the FAILED path on bad bytes.
"""

from unittest.mock import patch

import boto3

from shared import ddb
from shared.bedrock import SummaryResult
from summarize import handler as sm


def _s3_event(bucket: str, key: str) -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def test_happy_path_writes_summary_and_marks_done(bucket, table):
    ddb.put_pending(summary_id="h1", source_filename="x.txt")
    boto3.client("s3").put_object(
        Bucket=bucket, Key="uploads/h1.txt", Body=b"the quick brown fox"
    )

    fake = SummaryResult(
        text="# A summary",
        model_id="us.anthropic.claude-sonnet-4-6",
        input_tokens=10,
        output_tokens=5,
    )
    with patch.object(sm, "summarize_text", return_value=fake) as mock:
        sm.handler(_s3_event(bucket, "uploads/h1.txt"), None)

    mock.assert_called_once()
    row = ddb.get_summary(summary_id="h1")
    assert row["status"] == ddb.STATUS_DONE
    assert row["summary_s3_key"] == "summaries/h1.md"
    assert int(row["input_tokens"]) == 10
    assert int(row["output_tokens"]) == 5

    # The summary was actually written to S3.
    body = (
        boto3.client("s3")
        .get_object(Bucket=bucket, Key="summaries/h1.md")["Body"]
        .read()
        .decode("utf-8")
    )
    assert body == "# A summary"


def test_non_utf8_input_marks_failed_and_reraises(bucket, table):
    import pytest

    ddb.put_pending(summary_id="b1", source_filename="bad.txt")
    boto3.client("s3").put_object(Bucket=bucket, Key="uploads/b1.txt", Body=b"\xff\xfe")

    with pytest.raises(Exception):
        sm.handler(_s3_event(bucket, "uploads/b1.txt"), None)

    row = ddb.get_summary(summary_id="b1")
    assert row["status"] == ddb.STATUS_FAILED
    assert "UTF-8" in row["error_message"] or "utf-8" in row["error_message"]


def test_url_encoded_keys_are_decoded(bucket, table):
    """S3 events URL-encode special chars; the handler must decode before reading."""
    # Note: with UUID-only keys we don't actually hit this, but the logic should
    # still work if a key ever has +/spaces.
    ddb.put_pending(summary_id="u%20rl", source_filename="x.txt")
    boto3.client("s3").put_object(Bucket=bucket, Key="uploads/u rl.txt", Body=b"hello")
    fake = SummaryResult(text="ok", model_id="m", input_tokens=1, output_tokens=1)

    with patch.object(sm, "summarize_text", return_value=fake):
        # S3 events render space as '+'.
        sm.handler(_s3_event(bucket, "uploads/u+rl.txt"), None)
