"""
request_upload handler tests: POST /uploads issues a presigned URL and
seeds a PENDING DDB row. We don't need the URL to be a real one — just
confirm boto3 was asked to sign for the right key.
"""

import json
from unittest.mock import patch

import boto3

from request_upload import handler as ru
from shared import ddb


def _event(body=None, method="POST"):
    return {
        "httpMethod": method,
        "body": json.dumps(body) if body is not None else None,
    }


def test_post_returns_url_and_seeds_pending_row(bucket, table):
    with patch("boto3.client") as mock_client:
        s3 = mock_client.return_value
        s3.generate_presigned_url.return_value = "https://signed.example/url"

        resp = ru.handler(_event({"filename": "doc.txt"}), None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://signed.example/url"
    assert "summary_id" in body
    assert body["expires_in_seconds"] == ru.PRESIGNED_URL_EXPIRY_SECONDS

    # The presigned URL is for uploads/{summary_id}.txt in the right bucket.
    call = s3.generate_presigned_url.call_args
    assert call.args[0] == "put_object"
    assert call.kwargs["Params"]["Bucket"] == bucket
    assert call.kwargs["Params"]["Key"] == f"uploads/{body['summary_id']}.txt"

    # DDB row was seeded as PENDING.
    row = ddb.get_summary(summary_id=body["summary_id"])
    assert row is not None
    assert row["status"] == ddb.STATUS_PENDING
    assert row["source_filename"] == "doc.txt"


def test_post_falls_back_to_default_filename_when_body_is_garbage(bucket, table):
    with patch("boto3.client") as mock_client:
        mock_client.return_value.generate_presigned_url.return_value = "https://x"
        resp = ru.handler({"httpMethod": "POST", "body": "{not-json"}, None)

    body = json.loads(resp["body"])
    row = ddb.get_summary(summary_id=body["summary_id"])
    assert row["source_filename"] == "untitled.txt"


def test_options_returns_204_for_cors_preflight(bucket, table):
    resp = ru.handler({"httpMethod": "OPTIONS"}, None)
    assert resp["statusCode"] == 204
    assert "Access-Control-Allow-Origin" in resp["headers"]
