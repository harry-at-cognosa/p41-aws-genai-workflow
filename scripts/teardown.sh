#!/usr/bin/env bash
# Tear down the v1.0 stack and any retained data. Run when done demoing.
#
# Phase 1+ implementation will empty the S3 bucket explicitly before destroy.
# For now: cdk destroy is enough since no resources are deployed yet.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/infra"

# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate" 2>/dev/null || true

echo "==> cdk destroy"
cdk destroy --force
