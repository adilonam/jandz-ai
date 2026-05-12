"""Helpers for resume PDF parsing."""

from io import BytesIO

from pypdf import PdfReader


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract plain text from uploaded PDF bytes."""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return ""

    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks).strip()
