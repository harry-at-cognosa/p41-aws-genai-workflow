"""
End-to-end test that hits the deployed stack. Skipped unless API_BASE_URL
and API_KEY are set (for example, sourced from .env).

Run with:
    set -a; source .env; set +a
    pytest tests/integration -v -m integration
"""

import os
import time
from pathlib import Path

import pytest
import requests


pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def api():
    base = os.environ.get("API_BASE_URL")
    key = os.environ.get("API_KEY")
    if not base or not key:
        pytest.skip("API_BASE_URL and API_KEY must be set for integration tests")
    return base.rstrip("/") + "/", key


def _short_article() -> bytes:
    p = Path(__file__).resolve().parents[2] / "samples" / "short_article.txt"
    return p.read_bytes()


def test_full_round_trip(api):
    base, key = api
    headers = {"x-api-key": key}

    r = requests.post(
        base + "uploads",
        headers={**headers, "Content-Type": "application/json"},
        json={"filename": "short_article.txt"},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    summary_id = payload["summary_id"]
    upload_url = payload["upload_url"]

    put = requests.put(upload_url, data=_short_article(), timeout=20)
    assert put.status_code == 200, put.text

    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        poll = requests.get(base + f"summaries/{summary_id}", headers=headers, timeout=10)
        assert poll.status_code == 200, poll.text
        data = poll.json()
        if data["status"] in ("DONE", "FAILED"):
            break
    else:
        pytest.fail(f"timed out waiting for summary; last status={data.get('status')}")

    assert data["status"] == "DONE", data
    assert "TL;DR" in data["summary"]
    assert "Key points" in data["summary"]
    assert data["input_tokens"] > 0
    assert data["output_tokens"] > 0
    assert data["model_id"].startswith("us.anthropic.")


def test_unknown_id_returns_404(api):
    base, key = api
    r = requests.get(base + "summaries/00000000-0000-0000-0000-000000000000",
                     headers={"x-api-key": key}, timeout=10)
    assert r.status_code == 404
