"""
SummarizerStack — all AWS resources for p41-aws-genai-workflow v1.0.

Currently empty (Phase 0 scaffold). Phase 1 will add:
  - S3 bucket (uploads/, summaries/, web/ prefixes)
  - DynamoDB Summaries table
  - DLQ (SQS) for the summarize Lambda
  - IAM roles for the three Lambdas

Phase 2 wires the summarize Lambda + Bedrock; Phase 3 adds API Gateway and
the request_upload / get_summary Lambdas; Phase 4 adds CloudFront for the
demo frontend; Phase 5 adds CloudWatch alarms and a dashboard.
"""

from aws_cdk import Stack
from constructs import Construct


class SummarizerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Resources added in subsequent phases.
