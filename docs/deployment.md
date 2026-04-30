# Deployment

How to deploy this stack from scratch on a fresh machine, and how to tear it down cleanly.

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| AWS CLI v2 | account access, key retrieval | `brew install awscli` |
| AWS credentials | deploys go against your account | `aws configure` (or SSO) |
| Python 3.12 | matches the Lambda runtime | `brew install python@3.12` |
| Node.js (any 20+) | AWS CDK is a Node tool | `brew install node` |
| AWS CDK | infrastructure as code | `npm install -g aws-cdk` |
| `gh` CLI (optional) | only needed to create a GitHub repo | `brew install gh` |

Verify:
```bash
aws sts get-caller-identity     # confirms credentials work
cdk --version                    # 2.110+ recommended
python3 --version                # 3.12.x
```

## One-time per AWS account + region

CDK needs a small "bootstrap" stack in each account/region you deploy into. It creates a staging S3 bucket and IAM roles used by every CDK deploy.

```bash
cd infra
cdk bootstrap aws://<account-id>/us-west-2
```

This is idempotent — running it again on a bootstrapped account/region is a no-op.

### Bedrock model access

On accounts new to Anthropic models on Bedrock, the first invocation of any Claude model triggers a one-time **use case details** form:

1. Open the [Bedrock console](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2)
2. Navigate to **Chat / text playgrounds**
3. Pick a Claude model and run any prompt
4. AWS shows the form — fill it in, submit
5. Approval is usually instant for individual accounts

This must be done before `summarize` will succeed. The summarize Lambda will return `ResourceNotFoundException` until it's done.

## Deploy

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/requirements.txt

cd infra
cdk deploy --require-approval never
```

First deploy takes ~6 minutes (CloudFront distribution provisioning is the slow step; subsequent deploys are 30-60 seconds because CloudFront is reused).

### After-deploy: populate `.env`

The smoke-test script and frontend need the API base URL and API key. Stack outputs surface the URL and the API key's *ID*; the actual key *value* is fetched separately:

```bash
cd ..
API_BASE=$(aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiBaseUrl`].OutputValue' --output text)
KEY_ID=$(aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' --output text)
KEY=$(aws apigateway get-api-key --api-key "$KEY_ID" --include-value --query value --output text)

cat > .env <<EOF
AWS_REGION=us-west-2
API_BASE_URL=$API_BASE
API_KEY=$KEY
EOF
```

`.env` is gitignored. Don't commit it.

## Smoke test

```bash
./scripts/upload_test.sh samples/short_article.txt
```

Expected output: a `summary_id`, an upload progress line, a few PROCESSING polls, and a rendered markdown summary in ~5–10 seconds.

## Run the test suite

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                              # 29 unit tests, no AWS calls (~3s)
set -a; source .env; set +a
pytest -m integration               # 2 tests against the live stack (~15s)
```

## Use the web UI

```
$ aws cloudformation describe-stacks --stack-name SummarizerStack \
    --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' --output text
```

Open that URL. On first load, paste your API base URL and key into the config modal — values are stored in `localStorage` so subsequent visits skip the prompt.

## Iterate on Lambda code

After editing any file under `lambdas/`, re-run `cdk deploy` from `infra/`. CDK only re-publishes the asset that changed, so iteration is fast (typically 20-40 seconds per deploy).

## Iterate on the frontend

Same deal — edit `frontend/index.html` and `cdk deploy`. The `BucketDeployment` construct uploads the new file to S3 and invalidates the CloudFront cache automatically.

## Subscribe to alarms

Optional but recommended for any long-running demo:

```bash
ALARMS_TOPIC=$(aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlarmsTopicArn`].OutputValue' --output text)
aws sns subscribe --topic-arn "$ALARMS_TOPIC" \
  --protocol email --notification-endpoint your@email.com
```

Confirm the email AWS sends you. Now any DLQ message or Lambda error will email you.

## CloudWatch dashboard

```bash
aws cloudformation describe-stacks --stack-name SummarizerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' --output text
```

Open that URL in a browser. Six widgets: invocations, errors, summarize duration percentiles, DLQ depth, API request count, API 4XX/5XX.

## Teardown

```bash
./scripts/teardown.sh
```

Under the hood: `cdk destroy` plus the bucket's `auto_delete_objects=true` setting empties the S3 bucket as part of the destroy. Confirms before deleting.

What gets removed:
- All Lambda functions, IAM roles/policies
- API Gateway, API key, usage plan
- S3 bucket (auto-emptied)
- DynamoDB table
- CloudFront distribution
- SQS DLQ + SNS alarm topic
- CloudWatch alarms, dashboard, log groups

What stays in the account:
- CDK bootstrap stack (`CDKToolkit`) — useful for any other CDK project; remove with `aws cloudformation delete-stack --stack-name CDKToolkit` if you really want to.
- Any orphaned auto-created Lambda log groups from the pre-Phase-5 stack (cosmetic; empty after 14 days; safe to delete manually).

After teardown, monthly cost goes back to $0.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `cdk synth` fails with "no module named aws_cdk" | venv not active or not yet pip-installed | `source .venv/bin/activate && pip install -r infra/requirements.txt` |
| `ResourceNotFoundException` on first invocation | Anthropic use case form not submitted | See "Bedrock model access" above |
| `cdk deploy` says "BootstrapStack version is too old" | older bootstrap from a previous CDK version | rerun `cdk bootstrap` |
| 502 Bad Gateway from API Gateway | Lambda crashed at startup | `aws logs tail /aws/lambda/<fn-name> --since 5m` to see the traceback |
| 307 TemporaryRedirect when PUTing to presigned URL | S3 client wasn't using SigV4 + virtual-hosted-style addressing | Already fixed in `request_upload` handler; ensure your `aws-cdk-lib` is recent |
| CloudFront URL shows access denied | OAC bucket policy didn't propagate; or BucketDeployment hasn't completed | wait a minute; retry; check CloudFront's distribution status is `Deployed` |
