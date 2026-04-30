"""
File-format dispatcher for the summarize pipeline.

`extract_text(filename, raw_bytes)` returns the document body as a single
UTF-8 string regardless of input format. Heavy deps (pypdf, docx2txt) are
imported lazily so the request_upload and get_summary Lambdas — which
share the layer but never call this — don't pay the import cost.

PDF strategy: try native text extraction first via pypdf. If pypdf
returns nothing meaningful (image-only / scanned PDF), raise
InvalidDocumentError with a clear message. OCR fallback via Textract is
on the v1.1 roadmap (see docs/v2_roadmap.md).
"""

from __future__ import annotations

import io
import os

from .errors import InvalidDocumentError

# Files yielding less than this many non-whitespace chars from native PDF
# extraction are treated as image-only.
_PDF_MIN_USEFUL_CHARS = 20

ACCEPTED_EXTENSIONS = ("txt", "md", "pdf", "docx")


def extension_of(filename: str) -> str:
    """Lower-cased extension without the dot. '' if there is no extension."""
    name = os.path.basename(filename or "")
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def extract_text(filename: str, raw_bytes: bytes) -> str:
    """
    Dispatch on extension. Caller is responsible for ensuring `filename`
    bears a meaningful extension — for our pipeline that's the original
    filename the user uploaded, preserved through the S3 key.
    """
    ext = extension_of(filename)
    if ext in ("txt", "md", ""):
        return _extract_text_utf8(raw_bytes)
    if ext == "pdf":
        return _extract_pdf(raw_bytes)
    if ext == "docx":
        return _extract_docx(raw_bytes)
    raise InvalidDocumentError(
        f"unsupported file type {ext!r}; accepted: {', '.join(ACCEPTED_EXTENSIONS)}"
    )


def _extract_text_utf8(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidDocumentError("file is not valid UTF-8 text") from e


def _extract_pdf(raw_bytes: bytes) -> str:
    # Lazy import — only the summarize Lambda's deployment package has pypdf.
    from pypdf import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(io.BytesIO(raw_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            # Some pages can fail extraction individually (corrupt fonts,
            # unusual encodings). Skip them rather than failing the doc.
            page_text = ""
        if page_text:
            parts.append(page_text)
    text = "\n\n".join(parts).strip()
    if len(text.replace(" ", "").replace("\n", "")) < _PDF_MIN_USEFUL_CHARS:
        raise InvalidDocumentError(
            "PDF appears to be image-only or empty — no meaningful text could "
            "be extracted. OCR support (via AWS Textract) is on the v1.1 roadmap."
        )
    return text


def _extract_docx(raw_bytes: bytes) -> str:
    # Lazy import.
    import docx2txt  # type: ignore[import-not-found]

    text = (docx2txt.process(io.BytesIO(raw_bytes)) or "").strip()
    if not text:
        raise InvalidDocumentError("DOCX contains no extractable text")
    return text
