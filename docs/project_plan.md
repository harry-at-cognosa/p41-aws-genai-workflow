# v1.0 Project Plan — Build Schedule and Verification

This document describes the **build plan** for v1.0: how the work is sequenced, what each phase delivers, and how the end-to-end demo is verified.

For the system architecture, see `architecture.md`. For the v2.0 (FastAPI/Postgres) direction, see `v2_roadmap.md`.

---

## 1. Context

The repo is greenfield. The only spec is `AI-powered-document-summarization-workflow_on_AWS.md`: a small AWS PoC where a user uploads a text document, S3 stores it, a Lambda summarizes it via an LLM, and the summary is saved/returned.

**Goal**: a clean v1.0 (AWS Lambda + Bedrock + Claude) that demonstrates the workflow end-to-end and leaves obvious seams to grow into a multi-user FastAPI/Postgres "platform" v2.0 (modeled on `~/cognosa_web_app`, `~/1_listmgr`, `~/p51_local_automator`).

### Decisions locked

| Decision | Choice | Source |
|---|---|---|
| LLM provider | Amazon Bedrock + Claude | User clarification |
| Document types | Plain text (`.txt`, `.md`) only | User clarification (PDF/DOCX deferred to v2.0) |
| All other tech stack | Per `architecture.md` | AWS best practices |

---

## 2. Project structure

Mirrors `~/p51_local_automator` conventions (closest analog among the user's reference platforms — backend/frontend split, `requirements.txt`, `.env.example`, `scripts/`, `tests/`, `docs/`).

```
p41-aws-genai-workflow/
├── README.md                        # quickstart, deploy, teardown
├── CLAUDE.md                        # already exists — update post-build
├── .gitignore                       # already exists (includes 20000)
├── .env.example                     # AWS_REGION, BEDROCK_MODEL_ID, API_KEY (for client)
├── docs/
│   ├── AI-powered-document-summarization-workflow_on_AWS.md  # the spec
│   ├── architecture.md              # system architecture
│   ├── project_plan.md              # this file
│   ├── deployment.md                # cdk bootstrap → deploy → smoke test (written in Phase 6)
│   └── v2_roadmap.md                # FastAPI/Postgres direction
├── infra/                           # CDK Python
│   ├── app.py                       # CDK entrypoint
│   ├── cdk.json
│   ├── requirements.txt             # aws-cdk-lib, constructs
│   └── stacks/
│       ├── __init__.py
│       └── summarizer_stack.py      # all resources in one stack for v1.0
├── lambdas/
│   ├── shared/                      # packaged as a Lambda Layer
│   │   ├── __init__.py
│   │   ├── ddb.py                   # thin DynamoDB helpers
│   │   ├── s3util.py
│   │   ├── bedrock.py               # ◄ THE V2.0 SEAM: pure summarize_text(text, opts) -> str
│   │   ├── prompts.py               # prompt templates
│   │   ├── logging.py               # structured JSON logger
│   │   └── errors.py
│   ├── request_upload/
│   │   ├── handler.py
│   │   └── requirements.txt
│   ├── summarize/
│   │   ├── handler.py
│   │   └── requirements.txt
│   └── get_summary/
│       ├── handler.py
│       └── requirements.txt
├── frontend/
│   └── index.html                   # vanilla JS: upload via presigned PUT, poll, render
├── tests/
│   ├── unit/                        # pytest + moto
│   │   ├── test_request_upload.py
│   │   ├── test_summarize.py
│   │   ├── test_get_summary.py
│   │   └── test_bedrock.py          # mocks bedrock client
│   └── integration/
│       └── test_e2e.py              # runs against deployed stack via boto3 + requests
├── scripts/
│   ├── bootstrap.sh                 # cdk bootstrap, enable bedrock model access
│   ├── deploy.sh                    # cdk deploy + upload frontend to S3
│   ├── teardown.sh                  # cdk destroy + empty buckets
│   └── upload_test.sh               # curl-based smoke test: upload sample, poll, print summary
└── samples/
    ├── short_article.txt
    └── long_essay.md
```

---

## 3. Schedule

7 phases. **Estimated total: 16–22 hours of focused work**, plausibly across 4–6 sessions.

| # | Phase | Deliverable | Est. |
|---|---|---|---|
| 0 | **Bootstrap** | AWS account check; `cdk bootstrap` in `us-west-2`; first Bedrock Claude invocation (auto-enables model access — Anthropic may prompt for one-time use-case details); repo skeleton (folders, `.env.example`, empty CDK app); confirm `cdk synth` succeeds. | 1–2 h |
| 1 | **Core infra** | S3 bucket, DynamoDB table, IAM roles, DLQ, CloudWatch log groups. `cdk deploy` produces bucket + table; smoke test via console. | 2–3 h |
| 2 | **Summarize Lambda + Bedrock** | `summarize/handler.py`, `shared/bedrock.py`, S3 trigger wired up. Drop a `.txt` into `uploads/` via console → see summary appear in `summaries/` and DDB row flip to `DONE`. **This is the milestone that proves the core works.** | 3–4 h |
| 3 | **Upload + Get APIs** | `request_upload`, `get_summary`, API Gateway, API key. End-to-end works via `curl`. | 3–4 h |
| 4 | **Demo frontend** | `index.html` deployed; CloudFront distribution; cookie-free origin. Manual upload via browser yields rendered summary. | 2–3 h |
| 5 | **Hardening** | DLQ alarm, CloudWatch dashboard (invocations / errors / latency / Bedrock token counts), structured logs, retry on transient Bedrock throttles, basic input validation. | 2–3 h |
| 6 | **Tests + docs** | `pytest` unit suite green; `tests/integration/test_e2e.py` against deployed stack; README quickstart; `docs/deployment.md`; `scripts/teardown.sh` verified. | 2–3 h |

### Critical files to create / modify

- `infra/stacks/summarizer_stack.py` — all CDK resources
- `lambdas/shared/bedrock.py` — **the v2.0 seam**; keep pure
- `lambdas/shared/prompts.py` — prompt templates
- `lambdas/summarize/handler.py` — orchestrator
- `lambdas/request_upload/handler.py`, `lambdas/get_summary/handler.py`
- `frontend/index.html`
- `scripts/deploy.sh`, `scripts/teardown.sh`
- `tests/unit/test_*.py`
- `README.md`, `docs/deployment.md`

---

## 4. End-to-end verification

After Phase 6:

1. **Fresh deploy**: `./scripts/teardown.sh && ./scripts/deploy.sh` succeeds in a clean shell.
2. **Console upload** (Phase 2 milestone): drop `samples/short_article.txt` into `uploads/` via S3 console → within ~10 s a `.md` appears in `summaries/` and the DDB row shows `status=DONE`.
3. **API smoke test**: `./scripts/upload_test.sh samples/long_essay.md` posts to `/uploads`, uploads, polls, prints the rendered summary.
4. **Browser demo**: open the CloudFront URL, pick a `.txt`, see the summary render in < 15 s.
5. **Failure path**: upload a non-UTF8 binary file → DDB row goes to `FAILED` with a useful `error_message`; CloudWatch alarm on DLQ fires; subsequent uploads still work.
6. **Cost check**: CloudWatch shows < $1 spent for ~50 demo summaries (Sonnet) or < $0.10 (Haiku).
7. **Teardown**: `./scripts/teardown.sh` empties buckets and removes the stack with no orphaned resources.

---

## 5. Open questions deferred to build time (not blocking)

- Final Claude model on Bedrock at build time (Sonnet vs Haiku) — pick during Phase 2 based on summary quality vs cost on `samples/long_essay.md`.
- CloudFront vs raw S3 website hosting for the demo page — CloudFront if HTTPS matters for clipboard / file APIs in some browsers; otherwise S3 website is fine.
- Whether to add a tiny `/healthz` Lambda. Probably not worth it.
