# Test Plan — v1.0 + Phase 7

A step-by-step manual test of the **deployed** system. Walks through the demo from a fresh-user perspective and exercises the full pipeline plus failure paths and observability. Total time: ~15–20 minutes.

This document tests the **currently deployed** stack — no redeployment needed. To redeploy from scratch (e.g., after `./scripts/teardown.sh`), see `docs/deployment.md`.

---

## What you'll need

- A modern browser
- Optionally: a terminal with the `aws` CLI configured against account `033684811905` (only for tests 7–10)

You'll need two values to use the demo. **Get them once** and the browser remembers them in localStorage:

| Value | Source |
|---|---|
| **API base URL** | `https://5r97rncsj8.execute-api.us-west-2.amazonaws.com/v1/` |
| **API key** | run the command below, or copy it from `.env` if you already have it |

```bash
aws apigateway get-api-key --api-key flinxq1dck --include-value --query value --output text
```

The key is a 40-character random string. Treat it like a password — it's the only thing protecting your demo from public abuse.

---

## Test 1 — First visit, configure the page

1. Open **https://d2v3af47jflqb4.cloudfront.net/** in a browser (use Incognito/Private if you want to simulate a brand-new user; otherwise localStorage from a previous visit will skip this step).
2. **Expected**: a modal pops up titled "API configuration" with two empty fields.
3. Paste the API base URL and API key from above. Click **Save**.
4. **Expected**: the modal closes; the upload area is visible. The page should look clean, with a centered card containing a dashed-bordered "Choose a file or drop one here" area.

✅ **Pass criteria**: modal closed, no errors, upload area visible.

---

## Test 2 — Upload a plain-text file (golden path)

1. Click the upload area (or drag-and-drop). Pick `samples/short_article.txt` from this repo.
2. **Expected progression** in the status line below the card:
   - `Requesting upload URL…`
   - `Uploading short_article.txt…`
   - `status=PROCESSING (1.x s elapsed)` — yellow text
   - `done in 5–12 s` — green text
3. **Expected**: a "Summary" card appears below the status line containing:
   - A meta line with `model=us.anthropic.claude-sonnet-4-6`, input/output token counts (~390/250 for this doc), and elapsed time
   - A markdown-rendered summary with **TL;DR** (one paragraph), **Key points** (5 bullets), **Notable quotes** (1–2 quotes from the article)
4. The summary should mention Janet Pillai, Marco Lin, the cinnamon coffee, and the credential rotation.

✅ **Pass criteria**: summary renders within 15s; key facts from the article are correct (no hallucinations).

---

## Test 3 — Upload a markdown file (longer document)

1. Click the upload area again. Pick `samples/long_essay.md`.
2. **Expected**: same progression as Test 2 but slightly slower. ~8–15 seconds.
3. **Expected**: token counts are higher (~1500 in / ~300 out). Summary covers the office library reorganization story — Eleanor, Donald, Henrietta, the wooden box of library cards, the working group, the outcome.

✅ **Pass criteria**: summary correctly handles multi-section markdown input; longer document completes within 15s.

---

## Test 4 — Upload a PDF

1. Pick `samples/sample.pdf` (a small text-bearing PDF generated for testing).
2. **Expected**: same progression. Summary mentions "Phase 7 sample PDF", text extraction, and three short lines.
3. **Expected token counts**: ~140 in / ~150 out.

✅ **Pass criteria**: PDF text was extracted natively (via `pypdf`); summary is coherent.

> **Want to test image-only PDF rejection?** You'd need a scanned PDF with no embedded text. Drop it in and you should see `status=FAILED` with the message `"PDF appears to be image-only or empty — no meaningful text could be extracted. OCR support (via AWS Textract) is on the v1.1 roadmap."` This path is already covered in the unit tests (`test_extract_pdf_raises_when_no_meaningful_text`).

---

## Test 5 — Upload a DOCX (Word document)

1. Pick `samples/sample.docx`. Or use any real Word document you have handy (≤ 1 MB).
2. **Expected**: same progression. Summary describes the document content.
3. **Expected token counts** for `samples/sample.docx`: ~150 in / ~165 out.

✅ **Pass criteria**: Word document text was extracted (via `docx2txt`); summary is accurate.

---

## Test 6 — Try an unsupported file type

1. Try to drop an unsupported file. Easiest: any image (`.png`, `.jpg`) or spreadsheet (`.xlsx`, `.csv`).
2. **Expected**: the file picker `accept` filter may grey it out, but you can still drag-drop it.
3. **Expected status line**: red text saying something like:
   `POST /uploads failed: 400 {"error": "unsupported file type 'png'", "accepted": ["txt", "md", "pdf", "docx"]}`

✅ **Pass criteria**: server-side validation rejects with HTTP 400 and a clear message; the user is not allowed to upload garbage.

---

## Test 7 — CLI smoke test (alternative to the browser)

In your terminal, with the repo open and `.env` populated:

```bash
cd /Users/harry/p41-aws-genai-workflow
./scripts/upload_test.sh samples/short_article.txt
```

**Expected output**:
```
==> Requesting upload URL from https://5r97rncsj8.execute-api.us-west-2.amazonaws.com/v1
    summary_id=<uuid>
==> Uploading samples/short_article.txt to presigned URL
==> Polling GET /summaries/<uuid>
    [1] status=PENDING
    [2] status=PROCESSING
    [3] status=DONE

──────────── Summary ────────────
…(markdown summary)…
─────────────────────────────────
model=us.anthropic.claude-sonnet-4-6  input_tokens=389  output_tokens=~230
```

✅ **Pass criteria**: script exits 0; summary printed; token counts present.

Try it with `samples/sample.pdf` and `samples/sample.docx` too.

---

## Test 8 — Inspect the DynamoDB row for a completed summary

After Test 2/3/4/5, run (substitute the `summary_id` from any successful run):

```bash
TABLE=SummarizerStack-SummariesTable8DD3746B-16A6G1559I0BQ
SUMMARY_ID=<uuid-from-earlier-test>

aws dynamodb get-item --table-name "$TABLE" \
  --key "{\"summary_id\":{\"S\":\"$SUMMARY_ID\"}}" --output json \
  | python3 -c "import json,sys; item=json.load(sys.stdin)['Item']; print(json.dumps({k:list(v.values())[0] for k,v in item.items()}, indent=2))"
```

**Expected fields** (all present, types as scalar):
- `summary_id` — the UUID
- `status` — `DONE`
- `created_at`, `completed_at` — Unix epochs
- `expires_at` — `created_at + 30 days` (TTL)
- `source_filename` — the filename you uploaded
- `summary_s3_key` — `summaries/<uuid>.md`
- `model_id` — `us.anthropic.claude-sonnet-4-6`
- `input_tokens`, `output_tokens` — integers

✅ **Pass criteria**: row exists with all fields populated; schema looks like a clean port-target for a future Postgres `summaries` table.

---

## Test 9 — Open the CloudWatch dashboard

```bash
aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' --output text
```

Open that URL.

**Expected**: a CloudWatch dashboard named `SummarizerStack-overview` with six widgets:
1. Lambda invocations (sum/min)
2. Lambda errors (sum/min)
3. summarize duration p50/p95/p99 (ms)
4. DLQ depth (max/min)
5. API Gateway request count (sum/min)
6. API Gateway 4XX / 5XX (sum/min)

After Tests 2–7 you should see invocations on widget 1 (the summarize function spiking each time), the duration percentiles populated on widget 3, and request counts on widget 5. Widgets 2 and 4 should be flat at 0 (no errors); widget 6 may have a tick from Test 6 (the 400 error).

✅ **Pass criteria**: dashboard loads, all six widgets render data from your test runs.

---

## Test 10 — Check current alarm states

```bash
aws cloudwatch describe-alarms --alarm-name-prefix SummarizerStack \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output table
```

**Expected**:
```
+---------------------------------------+---------------------+
| SummarizerStack-GetSummary-Errors     |  OK                 |
| SummarizerStack-RequestUpload-Errors  |  OK                 |
| SummarizerStack-Summarize-Errors      |  OK                 |
| SummarizerStack-SummarizeDLQDepth     |  OK                 |
+---------------------------------------+---------------------+
```

> **Note**: alarms initialize as `INSUFFICIENT_DATA` until they have observed metric points. After running Tests 2–5 you should see `OK` for all four (or `INSUFFICIENT_DATA` if a Lambda hasn't been invoked recently — also fine).

✅ **Pass criteria**: no alarms in `ALARM` state.

---

## Test 11 — (Optional) Subscribe to email alerts

If you want to be notified of any future failure:

```bash
ALARMS_TOPIC=$(aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlarmsTopicArn`].OutputValue' --output text)

aws sns subscribe --topic-arn "$ALARMS_TOPIC" \
  --protocol email --notification-endpoint your@email.com
```

Confirm the email AWS sends you. Now any DLQ message or Lambda error will email you.

---

## Test 12 — Reconfigure the API key in the browser

1. Click the small **configure** link in the top right of the page.
2. **Expected**: the API configuration modal reopens with the existing values pre-filled.
3. Change the API URL to garbage (e.g., `https://wrong-url.example/`) and Save.
4. Try to upload anything.
5. **Expected**: the status line shows a red error like `POST /uploads failed: 0 ` or a CORS-related network error. The upload doesn't succeed.
6. Click **configure** again, restore the correct URL, Save.
7. Re-upload — should work.

✅ **Pass criteria**: bad config produces a visible error; correct config recovers the system.

---

## Pass / fail summary

If Tests 1–10 pass:
- The full v1.0 pipeline works end-to-end.
- All four document types are accepted.
- The failure path on bad input is visible to the user.
- Observability is wired up and queryable.

The system is ready for normal demo use.

---

## What to do next

- **Daily/weekly demos**: leave the stack running. Idle cost is ~$0/month.
- **Expecting a long pause**: tear down with `./scripts/teardown.sh`. Restart later via `docs/deployment.md` (~6 minutes for a fresh deploy).
- **Found a bug?** the `tests/unit/` suite (`pytest`) is fast; reproduce there and the fix is local. The `tests/integration/test_e2e.py` runs against the live stack and can confirm the fix is deployed.
