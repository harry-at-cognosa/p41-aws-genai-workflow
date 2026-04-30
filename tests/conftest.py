"""
Shared pytest setup. Adds the lambdas/ directory to PYTHONPATH so that:

  - tests can `import shared.bedrock` etc.
  - handler tests can do `from request_upload import handler` etc.

In production these imports work because the Lambda runtime puts the
shared layer at /opt/python/ (so `shared` is on sys.path) and each
handler's own folder is the working directory. We mirror that here.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = REPO_ROOT / "lambdas"

# The shared/ package lives at lambdas/shared/, so adding lambdas/ to
# sys.path makes `import shared` work the same way the Lambda layer does.
sys.path.insert(0, str(LAMBDAS))

# Each handler folder is also on sys.path so `from handler import handler`
# works in handler-level tests.
for sub in ("request_upload", "summarize", "get_summary"):
    sys.path.insert(0, str(LAMBDAS / sub))
