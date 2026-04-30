import boto3

from shared import ddb


def _row(table, summary_id):
    return boto3.resource("dynamodb").Table(table).get_item(Key={"summary_id": summary_id}).get("Item")


def test_put_pending_seeds_a_row(table):
    ddb.put_pending(summary_id="s1", source_filename="doc.txt", created_at=1700000000)
    row = _row(table, "s1")
    assert row["status"] == ddb.STATUS_PENDING
    assert row["source_filename"] == "doc.txt"
    assert int(row["created_at"]) == 1700000000
    # expires_at = created_at + 30d
    assert int(row["expires_at"]) == 1700000000 + 30 * 24 * 60 * 60


def test_state_machine_transitions(table):
    ddb.put_pending(summary_id="s2", source_filename="x.txt")
    ddb.mark_processing(summary_id="s2")
    assert _row(table, "s2")["status"] == ddb.STATUS_PROCESSING

    ddb.mark_done(
        summary_id="s2",
        summary_s3_key="summaries/s2.md",
        model_id="us.anthropic.claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
    )
    row = _row(table, "s2")
    assert row["status"] == ddb.STATUS_DONE
    assert row["summary_s3_key"] == "summaries/s2.md"
    assert int(row["input_tokens"]) == 100
    assert int(row["output_tokens"]) == 50


def test_mark_failed_caps_error_message_length(table):
    ddb.put_pending(summary_id="s3", source_filename="x.txt")
    long_msg = "x" * 5000
    ddb.mark_failed(summary_id="s3", error_message=long_msg)
    row = _row(table, "s3")
    assert row["status"] == ddb.STATUS_FAILED
    assert len(row["error_message"]) == 1024


def test_get_summary_returns_none_for_missing(table):
    assert ddb.get_summary(summary_id="never-seen") is None
