"""
SummarizerStack — all AWS resources for p41-aws-genai-workflow v1.0.

Phase 1 (current): S3 bucket + DynamoDB Summaries table + SQS DLQ + outputs.
Phase 2: summarize Lambda + Bedrock + S3 trigger.
Phase 3: API Gateway + request_upload + get_summary Lambdas.
Phase 4: CloudFront for the demo frontend.
Phase 5: CloudWatch alarms and dashboard.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct


class SummarizerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 bucket ────────────────────────────────────────────────────────
        # Holds three logical prefixes:
        #   uploads/{summary_id}.txt   — raw user-uploaded documents (lifecycle: 30d)
        #   summaries/{summary_id}.md  — generated summaries (lifecycle: 365d)
        #   web/                       — static demo frontend (Phase 4)
        # PoC settings: DESTROY + auto_delete_objects so `cdk destroy` actually
        # removes the bucket. Tighten for prod (RETAIN + manual cleanup).
        self.bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-uploads",
                    prefix="uploads/",
                    expiration=Duration.days(30),
                ),
                s3.LifecycleRule(
                    id="expire-summaries",
                    prefix="summaries/",
                    expiration=Duration.days(365),
                ),
            ],
            cors=[
                s3.CorsRule(
                    # Browser uploads via presigned PUT URL (Phase 3+).
                    # Permissive in v1.0; lock down to the CloudFront origin
                    # in Phase 4 once the demo URL is known.
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3000,
                ),
            ],
        )

        # ── DynamoDB Summaries table ─────────────────────────────────────────
        # PK: summary_id (UUID4 string).
        # TTL on expires_at — keeps the table self-cleaning without a sweeper.
        # On-demand billing — fits PoC traffic profile, no provisioning to tune.
        self.table = ddb.Table(
            self,
            "SummariesTable",
            partition_key=ddb.Attribute(
                name="summary_id",
                type=ddb.AttributeType.STRING,
            ),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── SQS Dead-letter queue for the summarize Lambda ───────────────────
        # Wired as the on-failure destination in Phase 2.
        # 14-day retention so failures aren't silently lost over a long weekend.
        self.dlq = sqs.Queue(
            self,
            "SummarizeDLQ",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )

        # ── Stack outputs ────────────────────────────────────────────────────
        # Surfaced by `cdk deploy` so scripts and developers don't have to hunt
        # for resource names in the console.
        CfnOutput(
            self,
            "BucketName",
            value=self.bucket.bucket_name,
            description="S3 bucket holding uploads/, summaries/, web/",
        )
        CfnOutput(
            self,
            "BucketArn",
            value=self.bucket.bucket_arn,
        )
        CfnOutput(
            self,
            "SummariesTableName",
            value=self.table.table_name,
            description="DynamoDB table tracking summary status + metadata",
        )
        CfnOutput(
            self,
            "SummariesTableArn",
            value=self.table.table_arn,
        )
        CfnOutput(
            self,
            "SummarizeDLQUrl",
            value=self.dlq.queue_url,
            description="SQS DLQ for summarize Lambda failures",
        )
