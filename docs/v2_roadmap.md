# v2.0 Roadmap — From AWS Serverless PoC to FastAPI/Postgres Platform

This document captures **where v1.0 is heading**: a multi-user FastAPI + PostgreSQL platform running on a Mac mini (modeled on `~/cognosa_web_app`, `~/1_listmgr`, `~/p51_local_automator`). The goal of writing this *before* v1.0 is built is to make sure v1.0's seams line up with where we're going — so v2.0 is a port, not a rewrite.

For v1.0 architecture, see `architecture.md`. For the v1.0 build plan, see `project_plan.md`.

---

## 1. The migration seam

The core idea: keep **summarization-core** pure and make **storage / transport / auth** pluggable. v1.0 implements the platform layer with AWS-native services; v2.0 swaps the platform layer for FastAPI/Postgres while reusing summarization-core unchanged.

| Layer | v1.0 (AWS) | v2.0 (FastAPI/Postgres on Mac mini) | Effort to port |
|---|---|---|---|
| **Summarization core** | `lambdas/shared/bedrock.py::summarize_text(text, *, model_id, max_tokens) -> SummaryResult` (pure function) | Same module imported by FastAPI route handlers | **Zero** |
| **Prompts** | `lambdas/shared/prompts.py` | Same module | **Zero** |
| **LLM provider** | Bedrock InvokeModel | Direct Anthropic API (or OpenAI) — same Messages API shape | Swap one client init |
| **HTTP transport** | API Gateway → 3 Lambdas | 3 FastAPI route handlers | Light port — handler bodies port nearly verbatim because business logic lives in `shared/` |
| **Metadata** | DynamoDB `Summaries` table | Postgres `summaries` table (SQLAlchemy + Alembic migration) | Near-1:1 column mapping; Alembic migration is mostly copy-paste from the DDB schema |
| **Body storage** | S3 `uploads/` and `summaries/` prefixes | Either keep S3 (cheap blob store accessed from Mac mini) **or** local FS / Postgres `bytea` | Interface in `shared/s3util.py` is small and replaceable |
| **Auth** | API Gateway API key (single tenant) | Cognito **or** session-based (matching `1_listmgr` pattern) + per-user scoping (`user_id` FK on summaries) | Net-new — design during v2.0 kickoff |
| **IaC** | AWS CDK | n/a (Mac mini); Docker Compose for service orchestration | n/a |
| **Frontend** | Static HTML on S3 + CloudFront | React (Vite) + FastAPI static serving, like `p51_local_automator` | Net-new |

---

## 2. Capabilities added in v2.0

Beyond simply porting v1.0:

- **Multi-user accounts**: office workers each have their own login. Summaries scoped by `user_id`.
- **Document types**: PDF (`pypdf`), DOCX (`python-docx`), and optionally scanned PDFs via Textract (or a local OCR engine if we want to stay off AWS for v2.0).
- **Persistent history**: every user sees their past summaries; can re-summarize with a different prompt.
- **Prompt-template versioning**: store templates in DB, allow per-user / per-document overrides.
- **Per-user usage quotas**: monthly token budget; tracked in Postgres.
- **Async job queue**: APScheduler (matching `p51_local_automator`) or Celery for long-running jobs (large PDFs).

Capabilities to evaluate but **not** assume:
- RAG / embeddings over the user's full document history (own product question).
- Streaming responses (nice UX; non-trivial through FastAPI).
- Going off AWS entirely (could keep Bedrock or move to direct Anthropic API).

---

## 3. What v1.0 must do to stay v2.0-friendly

These are the **non-negotiables** for v1.0 to keep the migration cheap:

1. **`summarize_text()` is a pure function** — no AWS imports, no S3, no DDB. Takes text, returns text. Lives in `lambdas/shared/bedrock.py`.
2. **Prompts live in code** (`lambdas/shared/prompts.py`), not in CDK config. v2.0 promotes them to a DB table without touching call sites.
3. **DDB schema mirrors a future Postgres table**: every attribute is a flat scalar (no nested maps unless they map cleanly to JSONB).
4. **S3 access is wrapped** in `lambdas/shared/s3util.py` so v2.0 can substitute a local filesystem or `bytea` backend by editing one file.
5. **No Lambda-specific globals leak into business logic**: handlers are thin shells that parse the event, call into `shared/`, and serialize the response.
6. **Use SSM Parameter Store or environment variables for config**, never hardcoded ARNs in business logic — makes the same code runnable locally with mocked AWS.

---

## 4. Out-of-scope for v1.0 (revisited)

To keep v1.0 tight, these are explicitly punted:

- VPC, Cognito, multi-tenant scoping
- PDF / DOCX support
- Streaming responses
- Prompt-version A/B testing
- RAG / embeddings
- A real frontend framework
- CI/CD pipeline (manual `scripts/deploy.sh` is fine for v1.0)

All of these get reconsidered at v2.0 kickoff.
