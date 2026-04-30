"""
extract_text() dispatches on the filename's extension. We exercise it
with real bytes (txt/md) and with mocked underlying libraries (pdf/docx)
to keep tests fast and deterministic.
"""

from unittest.mock import MagicMock, patch

import pytest

from shared.errors import InvalidDocumentError
from shared.extractors import (
    ACCEPTED_EXTENSIONS,
    extension_of,
    extract_text,
)


# ── extension_of ───────────────────────────────────────────────────────

def test_extension_lowercases_and_strips_dot():
    assert extension_of("doc.PDF") == "pdf"
    assert extension_of("notes.MD") == "md"


def test_extension_handles_no_extension():
    assert extension_of("README") == ""
    assert extension_of("") == ""


def test_extension_uses_basename():
    # Strip directory components before splitting.
    assert extension_of("uploads/abc-123.docx") == "docx"


# ── txt/md path ────────────────────────────────────────────────────────

def test_extract_txt_decodes_utf8():
    assert extract_text("note.txt", b"Hello, world.") == "Hello, world."


def test_extract_md_decodes_utf8():
    assert extract_text("note.md", "# Heading\n\ntext".encode("utf-8")) == "# Heading\n\ntext"


def test_extract_no_extension_falls_back_to_text():
    assert extract_text("README", b"plain") == "plain"


def test_extract_text_rejects_non_utf8():
    with pytest.raises(InvalidDocumentError):
        extract_text("file.txt", b"\xff\xfe\xfa")


# ── pdf path (mocked pypdf) ────────────────────────────────────────────

def _mock_pdf_with_pages(*page_texts):
    pages = [MagicMock(extract_text=MagicMock(return_value=t)) for t in page_texts]
    reader = MagicMock(pages=pages)
    return MagicMock(return_value=reader)


def test_extract_pdf_concatenates_page_text():
    fake_reader = _mock_pdf_with_pages("page one body", "page two body")
    with patch("pypdf.PdfReader", fake_reader):
        out = extract_text("doc.pdf", b"<fake bytes>")
    assert "page one body" in out
    assert "page two body" in out


def test_extract_pdf_raises_when_no_meaningful_text():
    # All pages return empty/whitespace — typical of image-only PDFs.
    fake_reader = _mock_pdf_with_pages("", "  \n ")
    with patch("pypdf.PdfReader", fake_reader):
        with pytest.raises(InvalidDocumentError) as exc:
            extract_text("scan.pdf", b"<fake>")
    assert "image-only" in str(exc.value).lower() or "ocr" in str(exc.value).lower()


def test_extract_pdf_skips_pages_that_throw():
    # One page throws (bad font, etc.); other pages still produce output.
    bad_page = MagicMock()
    bad_page.extract_text.side_effect = RuntimeError("can't parse this page")
    good_page = MagicMock()
    good_page.extract_text.return_value = "still got something useful"
    fake_reader = MagicMock(return_value=MagicMock(pages=[bad_page, good_page]))
    with patch("pypdf.PdfReader", fake_reader):
        out = extract_text("partly.pdf", b"<fake>")
    assert "still got something useful" in out


# ── docx path (mocked docx2txt) ────────────────────────────────────────

def test_extract_docx_returns_processed_text():
    with patch("docx2txt.process", return_value="document body text"):
        assert extract_text("memo.docx", b"<fake>") == "document body text"


def test_extract_docx_raises_when_empty():
    with patch("docx2txt.process", return_value=""):
        with pytest.raises(InvalidDocumentError):
            extract_text("empty.docx", b"<fake>")


# ── unsupported types ──────────────────────────────────────────────────

def test_extract_rejects_unsupported_extension():
    with pytest.raises(InvalidDocumentError) as exc:
        extract_text("data.xlsx", b"<fake>")
    msg = str(exc.value).lower()
    assert "unsupported" in msg
    for ext in ACCEPTED_EXTENSIONS:
        assert ext in msg
