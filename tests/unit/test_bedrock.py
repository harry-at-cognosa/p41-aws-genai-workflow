"""
The v2.0 seam: summarize_text() must stay pure (no AWS event types in
its signature) and must round-trip the Bedrock Anthropic Messages API
shape correctly.

Bedrock isn't well-supported by moto, so we monkey-patch the bedrock
client constructor inside shared.bedrock instead.
"""

import io
import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from shared import bedrock
from shared.errors import ModelInvocationError


def _bedrock_response(text: str, in_tokens: int = 10, out_tokens: int = 20):
    """Wrap a payload to look like what bedrock-runtime.invoke_model returns."""
    payload = {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens},
    }
    return {"body": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def _patch_client(monkeypatch, mock):
    monkeypatch.setattr(bedrock, "_client", lambda: mock)


def test_summarize_text_returns_text_and_token_counts(monkeypatch):
    mock = MagicMock()
    mock.invoke_model.return_value = _bedrock_response("# A summary", 42, 17)
    _patch_client(monkeypatch, mock)

    result = bedrock.summarize_text("doc body", model_id="us.anthropic.claude-sonnet-4-6")

    assert result.text == "# A summary"
    assert result.input_tokens == 42
    assert result.output_tokens == 17
    assert result.model_id == "us.anthropic.claude-sonnet-4-6"


def test_summarize_text_sends_anthropic_messages_shape(monkeypatch):
    mock = MagicMock()
    mock.invoke_model.return_value = _bedrock_response("ok")
    _patch_client(monkeypatch, mock)

    bedrock.summarize_text("body", model_id="some-model", max_output_tokens=999)

    sent = json.loads(mock.invoke_model.call_args.kwargs["body"])
    assert sent["anthropic_version"] == "bedrock-2023-05-31"
    assert sent["max_tokens"] == 999
    assert "summarizer" in sent["system"].lower()
    assert sent["messages"][0]["role"] == "user"
    assert "body" in sent["messages"][0]["content"]


def test_summarize_text_truncates_oversized_input(monkeypatch):
    mock = MagicMock()
    mock.invoke_model.return_value = _bedrock_response("ok")
    _patch_client(monkeypatch, mock)

    huge = "x" * (bedrock.MAX_INPUT_CHARS + 5000)
    bedrock.summarize_text(huge, model_id="m")

    sent = json.loads(mock.invoke_model.call_args.kwargs["body"])
    user_content = sent["messages"][0]["content"]
    # The user content includes the prompt template wrapping, so it's
    # longer than MAX_INPUT_CHARS but the document slot itself was
    # truncated to MAX_INPUT_CHARS.
    assert user_content.count("x") == bedrock.MAX_INPUT_CHARS


def test_summarize_text_rejects_empty_document(monkeypatch):
    _patch_client(monkeypatch, MagicMock())
    with pytest.raises(ModelInvocationError):
        bedrock.summarize_text("   \n\t  ", model_id="m")


def test_summarize_text_retries_on_throttle_then_succeeds(monkeypatch):
    mock = MagicMock()
    throttle = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "InvokeModel",
    )
    mock.invoke_model.side_effect = [throttle, _bedrock_response("ok")]
    _patch_client(monkeypatch, mock)
    monkeypatch.setattr("time.sleep", lambda *_: None)  # don't actually wait

    result = bedrock.summarize_text("body", model_id="m", max_retries=3)
    assert result.text == "ok"
    assert mock.invoke_model.call_count == 2


def test_summarize_text_does_not_retry_on_non_retryable(monkeypatch):
    mock = MagicMock()
    mock.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "InvokeModel"
    )
    _patch_client(monkeypatch, mock)

    with pytest.raises(ModelInvocationError):
        bedrock.summarize_text("body", model_id="m", max_retries=5)
    assert mock.invoke_model.call_count == 1
