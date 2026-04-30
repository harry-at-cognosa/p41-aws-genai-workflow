# p41-aws-genai-workflow

A small AWS-native serverless proof-of-concept: upload a plain-text document, summarize it via Claude on Amazon Bedrock, retrieve the summary via API or browser.

This is **v1.0** — a personal MVP. The intent is that v2.0 ports the same summarization core onto a multi-user FastAPI + PostgreSQL platform running on a Mac mini. See `docs/v2_roadmap.md`.

## Architecture (one-liner)

```
Browser → API Gateway → presigned URL → S3 → Lambda → Bedrock (Claude) → S3 + DynamoDB → API Gateway → Browser
```

Full details in `docs/architecture.md`.

## Prerequisites

- AWS account with credentials configured (`aws sts get-caller-identity` works)
- Default region `us-west-2` (or override via `AWS_REGION`)
- Python 3.12, Node.js (for AWS CDK), `gh` CLI
- AWS CDK installed globally: `npm install -g aws-cdk`

## Quick start

```bash
# 1. Set up Python env for the infra app
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/requirements.txt

# 2. One-time CDK bootstrap (creates CDK staging resources in your account)
cd infra && cdk bootstrap

# 3. Deploy
cdk deploy

# 4. Smoke test (after deploy outputs the API URL)
../scripts/upload_test.sh ../samples/short_article.txt
```

## Documentation

- `docs/architecture.md` — system architecture, components, data flow, IAM, prompts
- `docs/project_plan.md` — build phases, schedule, verification checklist
- `docs/v2_roadmap.md` — direction toward FastAPI/Postgres platform
- `docs/AI-powered-document-summarization-workflow_on_AWS.md` — original spec

## Teardown

```bash
./scripts/teardown.sh
```

Removes the stack, empties the S3 bucket, and deletes the DynamoDB table. Run when you're done demoing to keep AWS spend at $0.

## Status

v1.0 is in active development. Track progress against `docs/project_plan.md` Phase 0 → Phase 6.
