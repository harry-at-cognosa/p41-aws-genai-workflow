"""
SummarizerStack — all AWS resources for p41-aws-genai-workflow v1.0.

Phase 1: S3 bucket + DynamoDB Summaries table + SQS DLQ + outputs.
Phase 2 (current): Shared Lambda layer + summarize Lambda + S3 trigger.
Phase 3: API Gateway + request_upload + get_summary Lambdas.
Phase 4: CloudFront for the demo frontend.
Phase 5: CloudWatch alarms and dashboard.
"""

import os
import shutil
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from constructs import Construct

# Default Bedrock inference profile for v4.x Claude on Bedrock. Cross-region
# routing across us-east-1, us-east-2, us-west-2.
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Foundation models that the us. inference profiles route to. The Lambda IAM
# role must allow InvokeModel on each of these in addition to the profile ARN.
_FOUNDATION_MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


def _build_shared_layer_asset(repo_root: Path) -> Path:
    """
    Copy lambdas/shared/ into infra/_layer_build/python/shared/ so it can be
    used as a Lambda Layer asset. Lambda Layers expect the python packages
    to live under `python/` at the asset root.
    """
    layer_root = repo_root / "infra" / "_layer_build"
    target = layer_root / "python" / "shared"
    if layer_root.exists():
        shutil.rmtree(layer_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "lambdas" / "shared", target)
    return layer_root


class SummarizerStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repo_root = Path(__file__).resolve().parents[2]
        model_id = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)

        # ── S3 bucket ────────────────────────────────────────────────────────
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
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3000,
                ),
            ],
        )

        # ── DynamoDB Summaries table ─────────────────────────────────────────
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
        self.dlq = sqs.Queue(
            self,
            "SummarizeDLQ",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )

        # ── Shared Lambda layer ──────────────────────────────────────────────
        # Repackages lambdas/shared/ into the python/ structure that Lambda
        # Layers expect. Layer code lands at /opt/python in the runtime,
        # which is on sys.path — so handlers do `from shared import ...`.
        layer_asset_root = _build_shared_layer_asset(repo_root)
        self.shared_layer = lambda_.LayerVersion(
            self,
            "SharedLayer",
            code=lambda_.Code.from_asset(str(layer_asset_root)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="shared/ — pure summarization core, prompts, DDB and S3 helpers",
        )

        # ── summarize Lambda ─────────────────────────────────────────────────
        self.summarize_fn = lambda_.Function(
            self,
            "SummarizeFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(
                str(repo_root / "lambdas" / "summarize"),
            ),
            handler="handler.handler",
            layers=[self.shared_layer],
            memory_size=1024,
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            log_retention=logs.RetentionDays.TWO_WEEKS,
            environment={
                "DOCUMENTS_BUCKET": self.bucket.bucket_name,
                "SUMMARIES_TABLE": self.table.table_name,
                "BEDROCK_MODEL_ID": model_id,
                "LOG_LEVEL": "INFO",
                "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1",
            },
            on_failure=destinations.SqsDestination(self.dlq),
            description="Summarize a document via Bedrock Claude on S3 ObjectCreated.",
        )

        # ── IAM grants for summarize ─────────────────────────────────────────
        # Storage permissions are scoped to the right prefixes.
        self.bucket.grant_read(self.summarize_fn, objects_key_pattern="uploads/*")
        self.bucket.grant_put(self.summarize_fn, objects_key_pattern="summaries/*")
        self.table.grant(self.summarize_fn, "dynamodb:UpdateItem")

        # Bedrock cross-region inference profile: must allow InvokeModel on
        # both the profile ARN (regional, account-scoped) and the underlying
        # foundation model ARNs in each routed region.
        profile_arn = (
            f"arn:aws:bedrock:{self.region}:{self.account}:"
            f"inference-profile/{model_id}"
        )
        # The foundation model ID is the inference profile ID with the
        # `us.` prefix removed.
        bare_model_id = (
            model_id[len("us."):] if model_id.startswith("us.") else model_id
        )
        foundation_model_arns = [
            f"arn:aws:bedrock:{r}::foundation-model/{bare_model_id}"
            for r in _FOUNDATION_MODEL_REGIONS
        ]
        self.summarize_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[profile_arn, *foundation_model_arns],
            )
        )

        # ── S3 → summarize trigger ───────────────────────────────────────────
        # ObjectCreated:* on uploads/* — covers PUT, POST, multipart, and copy.
        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.summarize_fn),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # ── Stack outputs ────────────────────────────────────────────────────
        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "BucketArn", value=self.bucket.bucket_arn)
        CfnOutput(self, "SummariesTableName", value=self.table.table_name)
        CfnOutput(self, "SummariesTableArn", value=self.table.table_arn)
        CfnOutput(self, "SummarizeDLQUrl", value=self.dlq.queue_url)
        CfnOutput(self, "SummarizeFunctionName", value=self.summarize_fn.function_name)
        CfnOutput(self, "BedrockModelId", value=model_id)
