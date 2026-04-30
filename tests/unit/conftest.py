"""
Unit-test fixtures: dummy AWS env, moto-backed S3 + DynamoDB.
"""

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Pin fake AWS credentials and a region so boto3 doesn't sniff real ones."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


@pytest.fixture
def aws():
    """Open a moto context for any boto3 client/resource created inside."""
    with mock_aws():
        yield


@pytest.fixture
def bucket(aws, monkeypatch):
    """A moto S3 bucket wired up to s3util via DOCUMENTS_BUCKET env var."""
    name = "test-bucket"
    boto3.client("s3").create_bucket(
        Bucket=name,
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
    )
    monkeypatch.setenv("DOCUMENTS_BUCKET", name)
    return name


@pytest.fixture
def table(aws, monkeypatch):
    """A moto DynamoDB Summaries table wired via SUMMARIES_TABLE."""
    name = "test-summaries"
    boto3.client("dynamodb").create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "summary_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "summary_id", "KeyType": "HASH"}],
    )
    monkeypatch.setenv("SUMMARIES_TABLE", name)
    return name
