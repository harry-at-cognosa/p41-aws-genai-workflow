#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.summarizer_stack import SummarizerStack

app = cdk.App()

SummarizerStack(
    app,
    "SummarizerStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
    ),
    description="p41-aws-genai-workflow v1.0 — document summarization via Bedrock Claude",
)

app.synth()
