"""
SummarizerStack — all AWS resources for p41-aws-genai-workflow v1.0.

Phase 1: S3 bucket + DynamoDB Summaries table + SQS DLQ + outputs.
Phase 2: Shared Lambda layer + summarize Lambda + S3 trigger.
Phase 3 (current): API Gateway + request_upload + get_summary Lambdas + API key.
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
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from constructs import Construct

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
_FOUNDATION_MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


def _build_shared_layer_asset(repo_root: Path) -> Path:
    """Repackage lambdas/shared/ for use as a Lambda Layer (python/ at root)."""
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
        layer_asset_root = _build_shared_layer_asset(repo_root)
        self.shared_layer = lambda_.LayerVersion(
            self,
            "SharedLayer",
            code=lambda_.Code.from_asset(str(layer_asset_root)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="shared/ — pure summarization core, prompts, DDB and S3 helpers",
        )

        common_env = {
            "DOCUMENTS_BUCKET": self.bucket.bucket_name,
            "SUMMARIES_TABLE": self.table.table_name,
            "LOG_LEVEL": "INFO",
        }

        # ── summarize Lambda (S3-triggered) ──────────────────────────────────
        self.summarize_fn = lambda_.Function(
            self,
            "SummarizeFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(str(repo_root / "lambdas" / "summarize")),
            handler="handler.handler",
            layers=[self.shared_layer],
            memory_size=1024,
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            log_retention=logs.RetentionDays.TWO_WEEKS,
            environment={**common_env, "BEDROCK_MODEL_ID": model_id},
            on_failure=destinations.SqsDestination(self.dlq),
            description="Summarize a document via Bedrock Claude on S3 ObjectCreated.",
        )
        self.bucket.grant_read(self.summarize_fn, objects_key_pattern="uploads/*")
        self.bucket.grant_put(self.summarize_fn, objects_key_pattern="summaries/*")
        self.table.grant(self.summarize_fn, "dynamodb:UpdateItem")

        profile_arn = (
            f"arn:aws:bedrock:{self.region}:{self.account}:"
            f"inference-profile/{model_id}"
        )
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

        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.summarize_fn),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # ── request_upload Lambda (POST /uploads) ────────────────────────────
        self.request_upload_fn = lambda_.Function(
            self,
            "RequestUploadFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(str(repo_root / "lambdas" / "request_upload")),
            handler="handler.handler",
            layers=[self.shared_layer],
            memory_size=256,
            timeout=Duration.seconds(10),
            log_retention=logs.RetentionDays.TWO_WEEKS,
            environment=common_env,
            description="Issue a presigned S3 PUT URL and seed a PENDING DDB row.",
        )
        # Lambda role needs s3:PutObject on uploads/* because that's what
        # the presigned URL is signed for. The Lambda itself never writes
        # the bytes — the client does — but the URL inherits the role.
        self.bucket.grant_put(self.request_upload_fn, objects_key_pattern="uploads/*")
        self.table.grant(self.request_upload_fn, "dynamodb:PutItem")

        # ── get_summary Lambda (GET /summaries/{id}) ─────────────────────────
        self.get_summary_fn = lambda_.Function(
            self,
            "GetSummaryFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(str(repo_root / "lambdas" / "get_summary")),
            handler="handler.handler",
            layers=[self.shared_layer],
            memory_size=256,
            timeout=Duration.seconds(5),
            log_retention=logs.RetentionDays.TWO_WEEKS,
            environment=common_env,
            description="Return summary status and (when DONE) the summary body.",
        )
        self.bucket.grant_read(self.get_summary_fn, objects_key_pattern="summaries/*")
        self.table.grant(self.get_summary_fn, "dynamodb:GetItem")

        # ── API Gateway ──────────────────────────────────────────────────────
        # REST API with API-key required on both methods. Permissive CORS so
        # the Phase 4 static frontend can call it from any origin during dev.
        self.api = apigw.RestApi(
            self,
            "SummarizerApi",
            rest_api_name="p41-summarizer",
            description="p41-aws-genai-workflow v1.0 public API",
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_rate_limit=10,
                throttling_burst_limit=20,
                metrics_enabled=True,
                # Stage-level execution logging (logging_level) requires an
                # account-wide CloudWatch role that's intentionally not set
                # in this account. The per-Lambda CloudWatch logs cover the
                # debugging we need for v1.0; revisit in Phase 5 hardening.
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "x-api-key"],
                max_age=Duration.seconds(3000),
            ),
        )

        method_options = apigw.MethodOptions(api_key_required=True)

        uploads = self.api.root.add_resource("uploads")
        uploads.add_method(
            "POST",
            apigw.LambdaIntegration(self.request_upload_fn, proxy=True),
            method_responses=[apigw.MethodResponse(status_code="201")],
            api_key_required=True,
        )

        summaries = self.api.root.add_resource("summaries")
        summary_by_id = summaries.add_resource("{id}")
        summary_by_id.add_method(
            "GET",
            apigw.LambdaIntegration(self.get_summary_fn, proxy=True),
            method_responses=[apigw.MethodResponse(status_code="200")],
            api_key_required=True,
        )

        # API key + usage plan. The key value is retrieved post-deploy:
        #   aws apigateway get-api-key --api-key <id> --include-value
        self.api_key = apigw.ApiKey(
            self,
            "PrimaryApiKey",
            description="Primary key for personal use of p41-summarizer v1",
        )
        plan = self.api.add_usage_plan(
            "DefaultUsagePlan",
            name="p41-default",
            throttle=apigw.ThrottleSettings(rate_limit=10, burst_limit=20),
            quota=apigw.QuotaSettings(
                limit=10_000,
                period=apigw.Period.MONTH,
            ),
        )
        plan.add_api_key(self.api_key)
        plan.add_api_stage(stage=self.api.deployment_stage)

        # ── Stack outputs ────────────────────────────────────────────────────
        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "BucketArn", value=self.bucket.bucket_arn)
        CfnOutput(self, "SummariesTableName", value=self.table.table_name)
        CfnOutput(self, "SummariesTableArn", value=self.table.table_arn)
        CfnOutput(self, "SummarizeDLQUrl", value=self.dlq.queue_url)
        CfnOutput(self, "SummarizeFunctionName", value=self.summarize_fn.function_name)
        CfnOutput(self, "BedrockModelId", value=model_id)
        CfnOutput(self, "ApiBaseUrl", value=self.api.url)
        CfnOutput(self, "ApiKeyId", value=self.api_key.key_id)
