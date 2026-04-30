# p41-aws-genai-workflow

Small AWS-native serverless proof-of-concept: upload a `.txt`, `.md`, `.pdf`, or `.docx` document, summarize it via Claude on Amazon Bedrock, retrieve the summary via API or browser. End-to-end in ~10 seconds. ~$0.005 per summary.

This is **v1.0** — a personal MVP. v2.0 ports the same summarization core onto a multi-user FastAPI + PostgreSQL platform on a Mac mini. See `docs/v2_roadmap.md`.

## Architecture

```
Browser (CloudFront) → API Gateway → request_upload Lambda
                              ↓
        S3 (uploads/) ──┐     │ presigned PUT URL + summary_id
                        │     │
                        ▼     ▼
                  summarize Lambda → Bedrock Claude (Sonnet 4.6)
                        ↓
        S3 (summaries/) + DynamoDB (status, tokens, model_id)
                        ↑
        Browser ← API Gateway ← get_summary Lambda
```

Detail in `docs/architecture.md`. Build phases and verification in `docs/project_plan.md`.

## Live demo

| | |
|---|---|
| Frontend | https://d2v3af47jflqb4.cloudfront.net/ |
| API base | `https://5r97rncsj8.execute-api.us-west-2.amazonaws.com/v1/` |
| Region | `us-west-2` |
| Account | `033684811905` |

The frontend prompts for the API base URL + API key on first load (stored in `localStorage`).
Retrieve the API key value:
```bash
aws apigateway get-api-key --api-key flinxq1dck --include-value --query value --output text
```

## Project layout

```
infra/         # CDK Python stack (one stack: SummarizerStack)
lambdas/
  shared/      # ◄ THE V2.0 SEAM: pure summarize_text(), prompts, DDB/S3 helpers
  request_upload/, summarize/, get_summary/  # thin handlers
frontend/      # single static HTML page, no build step
scripts/       # deploy.sh, teardown.sh, upload_test.sh
samples/       # short_article.txt, long_essay.md
tests/
  unit/        # 29 tests, ~3s, moto-backed
  integration/ # 2 tests against the deployed stack
docs/          # architecture, project_plan, v2_roadmap, deployment
```

## Quickstart

```bash
# 1. Set up Python env for the infra app
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/requirements.txt -r requirements-dev.txt

# 2. One-time CDK bootstrap (per AWS account + region)
cd infra && cdk bootstrap

# 3. Deploy
cdk deploy --require-approval never
cd ..

# 4. Populate .env from stack outputs (API_BASE_URL = ApiBaseUrl,
#    API_KEY = aws apigateway get-api-key --api-key <ApiKeyId> --include-value --query value --output text)

# 5. Smoke test
./scripts/upload_test.sh samples/short_article.txt
```

Full setup walkthrough in `docs/deployment.md`.

## Tests

```bash
pytest                                # unit tests (29, no AWS calls; ~3s)
set -a; source .env; set +a
pytest -m integration                 # hits the deployed stack (~15s)
```

## Teardown

```bash
./scripts/teardown.sh
```

Empties the S3 bucket, removes the stack, deletes the DynamoDB table. Total monthly cost goes back to $0.

## Cost

| | |
|---|---|
| Idle | ~$0/month (everything except CloudFront free-tier-eligible at PoC volumes) |
| Per summary | ~$0.005 (Sonnet 4.6, ~400 tokens in / ~250 out for a short article) |
| 100 summaries / month | < $1/month |

## Status

v1.0 complete. Phases 0–6 all shipped.

| Phase | Deliverable |
|---|---|
| 0 | Bootstrap, CDK app, GitHub repo |
| 1 | S3 bucket + DynamoDB table + DLQ |
| 2 | summarize Lambda + Bedrock + S3 trigger (**core works**) |
| 3 | API Gateway + request_upload + get_summary + API key |
| 4 | CloudFront-served demo frontend |
| 5 | CloudWatch alarms + dashboard + hardened logger |
| 6 | Pytest unit + integration suite + polished docs |
| 7 | PDF + DOCX support via in-Lambda native extraction |

### Accepted file types

| Type | How it's extracted |
|---|---|
| `.txt`, `.md` | UTF-8 decode |
| `.pdf` | `pypdf` native text extraction. Image-only/scanned PDFs are rejected with a clear message; OCR via AWS Textract is on the v1.1 roadmap. |
| `.docx` | `docx2txt` |

## Documentation

- `docs/architecture.md` — system architecture, IAM, prompts, failure handling
- `docs/project_plan.md` — phases and verification checklist
- `docs/v2_roadmap.md` — direction toward FastAPI/Postgres platform
- `docs/deployment.md` — new-machine onboarding
- `docs/AI-powered-document-summarization-workflow_on_AWS.md` — original spec
