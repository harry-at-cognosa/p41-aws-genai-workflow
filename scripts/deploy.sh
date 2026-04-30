#!/usr/bin/env bash
# Deploy the v1.0 stack to AWS. Run from the repo root.
#
# Idempotent: safe to re-run; CDK will compute the diff and apply only changes.
# Phase 1+ implementation will flesh out the steps; for now it just runs cdk deploy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/infra"

if [ ! -d "$REPO_ROOT/.venv" ]; then
  echo "==> Creating Python venv at .venv"
  python3 -m venv "$REPO_ROOT/.venv"
fi

# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"
pip install -q -r requirements.txt

# Silence the CDK "untested Node version" warning if running on a newer Node.
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1

echo "==> cdk synth (validating)"
cdk synth >/dev/null

echo "==> cdk deploy"
cdk deploy --require-approval never
