import boto3
import pytest

from shared import s3util
from shared.errors import InvalidDocumentError


def test_parse_summary_id_strips_prefix_and_extension():
    assert s3util.parse_summary_id_from_key("uploads/abc123.txt") == "abc123"
    assert s3util.parse_summary_id_from_key("uploads/abc123.md") == "abc123"
    assert s3util.parse_summary_id_from_key("uploads/no-extension") == "no-extension"


def test_parse_summary_id_rejects_unexpected_prefix():
    with pytest.raises(ValueError):
        s3util.parse_summary_id_from_key("summaries/abc123.md")


def test_read_text_decodes_utf8(bucket):
    boto3.client("s3").put_object(
        Bucket=bucket, Key="uploads/x.txt", Body="hello, world\n".encode("utf-8")
    )
    assert s3util.read_text(key="uploads/x.txt") == "hello, world\n"


def test_read_text_rejects_non_utf8(bucket):
    # 0xFF is not a valid UTF-8 byte sequence.
    boto3.client("s3").put_object(Bucket=bucket, Key="uploads/bad.txt", Body=b"\xff\xfe\xfa")
    with pytest.raises(InvalidDocumentError):
        s3util.read_text(key="uploads/bad.txt")


def test_write_summary_round_trips(bucket):
    key = s3util.write_summary(summary_id="abc", text="# Hello\n\nbody")
    assert key == "summaries/abc.md"
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    assert body.decode("utf-8") == "# Hello\n\nbody"
