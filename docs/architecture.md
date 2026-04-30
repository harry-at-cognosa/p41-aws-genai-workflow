# v1.0 Architecture — AWS Document Summarization Workflow

This document describes the **system architecture** for v1.0: an AWS-native serverless PoC that ingests a plain-text document, summarizes it via Claude on Bedrock, and returns the result.

For the build schedule, see `project_plan.md`. For the v2.0 (FastAPI/Postgres) direction, see `v2_roadmap.md`.

---

## 1. Tech stack

| Concern | Choice | Why |
|---|---|---|
| **IaC** | AWS CDK in Python | Matches Lambda runtime; better than SAM for extensibility; first-class Python typing. |
| **Lambda runtime** | Python 3.12 | Strong Bedrock SDK support; user's primary language. |
| **Upload trigger** | API Gateway (REST) → presigned S3 PUT URL → S3 ObjectCreated event → summarize Lambda | Decouples upload from processing; client uploads directly to S3 (no API Gateway / Lambda payload limits); idiomatic AWS pattern. |
| **LLM** | Amazon Bedrock — Claude (Sonnet 4.5 default; Haiku as a cost-mode toggle) | AWS-native, IAM-only auth, traffic stays in AWS. |
| **Body storage** | S3 (`uploads/` and `summaries/` prefixes) | Cheap blob store; same bucket survives unchanged into v2.0. |
| **Metadata storage** | DynamoDB single table (`Summaries`) | Lightweight, serverless, 1:1 mappable to a Postgres table in v2.0. |
| **Output API** | API Gateway `GET /summaries/{id}` | Returns status + summary text inline (or presigned GET URL if large). |
| **Auth (v1.0)** | API Gateway API key on a usage plan | Personal MVP — Cognito is overkill at this scale. |
| **Frontend** | Single static HTML page on S3 + CloudFront | Demonstrates upload → poll → render loop with no build step. |
| **Observability** | CloudWatch Logs (structured JSON) + Lambda error alarm + DLQ on summarize Lambda | Standard serverless observability. |
| **Region** | `us-west-2` | Matches user's default AWS region; Bedrock + Claude fully supported. |
| **Tests** | `pytest` + `moto` (unit); `cdk synth` snapshot (infra); `tests/integration/test_e2e.py` against deployed stack | |

**Explicitly NOT in v1.0**: VPC, Cognito, multi-tenant scoping, PDF/DOCX, streaming responses, prompt-version A/B, RAG/embeddings.

---

## 2. Data flow

```
┌──────────┐   1. POST /uploads               ┌──────────────────┐
│  Browser │ ───────────────────────────────► │  API Gateway     │
│ (static  │ ◄─── presigned PUT URL +         │     │            │
│  page)   │      summary_id                  │     ▼            │
└────┬─────┘                                  │  request_upload  │
     │                                        │     Lambda       │
     │ 2. PUT bytes to presigned URL          │     │            │
     ▼                                        │     ▼            │
┌──────────────────────────┐                  │  DynamoDB:       │
│ S3 bucket                │                  │  Summaries       │
│   uploads/{summary_id}   │                  │  (status=PENDING)│
│   summaries/{summary_id} │                  └──────────────────┘
└────┬─────────────────────┘
     │ 3. ObjectCreated event on uploads/*
     ▼
┌──────────────────────┐    4. InvokeModel    ┌──────────────┐
│ summarize Lambda     │ ───────────────────► │   Bedrock    │
│  - read object       │ ◄─────────────────── │   Claude     │
│  - call Bedrock      │       summary text   └──────────────┘
│  - write summaries/  │
│  - update DDB → DONE │
└──────────────────────┘

(later)  Browser polls GET /summaries/{id} → API GW → get_summary Lambda → DDB → returns body
```

---

## 3. Components

### 3.1 Lambdas

#### `request_upload` — `POST /uploads`
- Generates `summary_id` (UUID4).
- Validates content-type (`text/plain`, `text/markdown`) and max size (1 MB).
- Generates a presigned S3 PUT URL (5-minute expiry) for `uploads/{summary_id}.txt`.
- Writes DDB row: `{summary_id, status: "PENDING", created_at, source_filename}`.
- Returns `{summary_id, upload_url}`.
- **Memory**: 256 MB. **Timeout**: 10 s.

#### `summarize` — triggered by S3 `ObjectCreated:*` on `uploads/*`
- Parses `summary_id` from object key.
- Updates DDB → `status: "PROCESSING"`.
- Reads object bytes from S3, decodes UTF-8 (rejects non-UTF8 → `FAILED`).
- Truncates to model context budget (~100 KB ≈ ~25k tokens, well under Claude's window).
- Calls Bedrock `InvokeModel` (Anthropic Messages API format).
- Writes summary text to `summaries/{summary_id}.md`.
- Updates DDB → `{status: "DONE", summary_s3_key, completed_at, model_id, input_tokens, output_tokens}`.
- On any exception: DDB → `{status: "FAILED", error_message}`, then re-raises so the failure also lands in the DLQ.
- **Memory**: 1024 MB. **Timeout**: 60 s. **Reserved concurrency**: 5 (cost guardrail).
- **DLQ**: SQS queue, 14-day retention. CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0`.

#### `get_summary` — `GET /summaries/{id}`
- Reads DDB row by `summary_id`.
- If `DONE`: fetches summary body from S3, returns inline (text < 100 KB) or as a presigned GET URL.
- If `PENDING/PROCESSING`: returns status only (client polls).
- If `FAILED`: returns status + sanitized error message.
- **Memory**: 256 MB. **Timeout**: 5 s.

### 3.2 Storage

**S3 bucket** `p41-summarizer-{account}-{region}`
- Block all public access; SSE-S3 encryption.
- Prefixes: `uploads/`, `summaries/`, `web/` (frontend).
- Lifecycle: delete `uploads/*` after 30 days; delete `summaries/*` after 365 days.
- CORS: allow `PUT` from the demo page origin.

**DynamoDB table** `Summaries`
- PK: `summary_id` (S). On-demand billing.
- Attributes: `status`, `created_at`, `completed_at`, `source_filename`, `summary_s3_key`, `model_id`, `input_tokens`, `output_tokens`, `error_message`, `expires_at`.
- TTL on `expires_at` (set to 30 days from `created_at`) — keeps the table self-cleaning.

### 3.3 IAM (least privilege)

| Role | Permissions |
|---|---|
| `request_upload` | `s3:PutObject` on `uploads/*`; `dynamodb:PutItem` on `Summaries`. |
| `summarize` | `s3:GetObject` on `uploads/*`; `s3:PutObject` on `summaries/*`; `dynamodb:UpdateItem` on `Summaries`; `bedrock:InvokeModel` scoped to the chosen Claude model ARN; `sqs:SendMessage` on DLQ. |
| `get_summary` | `s3:GetObject` on `summaries/*`; `dynamodb:GetItem` on `Summaries`. |

---

## 4. Prompt design

Single template, parameterized by output style. Lives in `lambdas/shared/prompts.py` (code, not config) for v1.0; can be promoted to DDB or Parameter Store in v2.0.

```python
SYSTEM = (
    "You are a precise document summarizer. Produce summaries that preserve "
    "the document's claims and structure. Do not invent facts. Quote sparingly."
)

USER_TEMPLATE = """\
Summarize the following document.

Output format (markdown):
1. **TL;DR** — two sentences.
2. **Key points** — 5 bullets, each one sentence.
3. **Notable quotes** — up to 2, only if directly material.

Document:
<<<
{document}
>>>
"""
```

Bedrock-hosted Claude accepts the same Anthropic Messages API shape (`anthropic_version`, `messages`, `max_tokens`, `system`), so the prompt is portable to a direct Anthropic API call without changes — useful for v2.0.

---

## 5. Demo frontend

One file (`frontend/index.html`), no build step:

1. File picker (accepts `.txt, .md`).
2. `POST /uploads` → receive presigned URL + `summary_id`.
3. `PUT` file to presigned URL.
4. Poll `GET /summaries/{id}` every 2 s until `DONE` or `FAILED`.
5. Render markdown summary using `marked` from a CDN.

Hosted from the same S3 bucket under `web/` prefix, served via CloudFront. API key is either prompted in-page or baked in at build via a tiny substitution step in `scripts/deploy.sh`.

---

## 6. Failure handling

| Failure | Surface |
|---|---|
| Upload exceeds size or wrong content-type | Rejected by `request_upload` before presigning; HTTP 400. |
| Non-UTF8 body | `summarize` sets DDB `FAILED` with `error_message`; client sees clean error on poll. |
| Bedrock throttle | `summarize` retries with exponential backoff (3 attempts); persists `FAILED` only after exhaustion. |
| Bedrock unavailable / model not enabled | `summarize` raises; lands in DLQ; alarm fires. |
| Lambda timeout | Lambda re-invocation policy is "no retry" for S3 events that pass through async; we set the destination to DLQ explicitly. |
| Polling a non-existent `summary_id` | `get_summary` returns 404. |
