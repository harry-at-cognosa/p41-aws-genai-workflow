from shared.prompts import SYSTEM, USER_TEMPLATE, render_user_message


def test_render_substitutes_document():
    out = render_user_message("Hello world.")
    assert "Hello world." in out
    assert "<<<" in out and ">>>" in out  # delimiters preserved


def test_render_uses_template():
    # Sanity: the rendered message includes the structural cues from the template.
    out = render_user_message("anything")
    assert "TL;DR" in out
    assert "Key points" in out
    assert "Notable quotes" in out


def test_system_is_terse_and_constrains_hallucination():
    # Lightweight contract test for the system prompt.
    assert "summarizer" in SYSTEM.lower()
    assert "Do not invent" in SYSTEM


def test_template_has_a_document_slot():
    assert "{document}" in USER_TEMPLATE
