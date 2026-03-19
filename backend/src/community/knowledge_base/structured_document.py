"""Structured document helpers for ingestion and indexing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STRUCTURED_DOCUMENT_SUFFIX = ".structured.json"
BOOK_PAGE_START_PDF_PAGE_HINT = "book_page_start_pdf_page"
BOOK_PAGE_START_VALUE_HINT = "book_page_start_value"


def derive_structured_filename(source_filename: str) -> str:
    """Return the structured JSON filename derived from a source filename."""
    return f"{source_filename}{STRUCTURED_DOCUMENT_SUFFIX}"


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_positive_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def build_page_reference(pdf_page_no: int, hints: dict[str, str] | None = None) -> dict[str, Any]:
    """Return page numbering metadata for a physical PDF page."""
    hints = hints or {}
    start_pdf_page = _parse_positive_int(hints.get(BOOK_PAGE_START_PDF_PAGE_HINT))
    start_book_page = _parse_positive_int(hints.get(BOOK_PAGE_START_VALUE_HINT))

    book_page_no: int | None = None
    page_no: int | None
    page_number_source: str
    if (
        start_pdf_page is not None
        and start_book_page is not None
    ):
        if pdf_page_no >= start_pdf_page:
            book_page_no = start_book_page + (pdf_page_no - start_pdf_page)
            page_no = book_page_no
            page_number_source = "book"
        else:
            page_no = None
            page_number_source = "unmapped_pdf"
    else:
        page_no = pdf_page_no
        page_number_source = "pdf"

    return {
        "page_no": page_no,
        "pdf_page_no": pdf_page_no,
        "book_page_no": book_page_no,
        "page_number_source": page_number_source,
    }


def build_bbox(*, x: float, y: float, width: float, height: float) -> dict[str, float]:
    """Create a normalized bbox object."""
    return {
        "x": round(float(x), 2),
        "y": round(float(y), 2),
        "width": round(float(width), 2),
        "height": round(float(height), 2),
    }


def build_bbox_from_position(position: Any) -> dict[str, float] | None:
    """Convert a raw [x, y, width, height] position array into bbox metadata."""
    if not isinstance(position, (list, tuple)) or len(position) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in position)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return build_bbox(x=x, y=y, width=width, height=height)


def build_structured_document(
    *,
    source_filename: str,
    title: str,
    text: str,
    parser_name: str,
    hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a structured JSON document from extracted text."""
    hints = hints or {}
    normalized_text = _normalize_text(text)
    page_texts = normalized_text.split("\f") if "\f" in normalized_text else [normalized_text]

    pages: list[dict[str, Any]] = []
    global_line_number = 1
    paragraph_no_in_doc = 1

    for page_index, page_text in enumerate(page_texts, start=1):
        page_reference = build_page_reference(page_index, hints)
        page_lines = page_text.splitlines()
        paragraphs: list[dict[str, Any]] = []
        paragraph_lines: list[str] = []
        paragraph_line_start: int | None = None
        paragraph_no_on_page = 1

        def flush_paragraph(current_line_no: int) -> None:
            nonlocal paragraph_no_on_page, paragraph_no_in_doc, paragraph_lines, paragraph_line_start
            if not paragraph_lines or paragraph_line_start is None:
                paragraph_lines = []
                paragraph_line_start = None
                return
            paragraph_text = "\n".join(paragraph_lines).strip()
            if paragraph_text:
                paragraphs.append(
                    {
                        "paragraph_id": f"page-{page_reference['pdf_page_no']}-p{paragraph_no_on_page}",
                        "paragraph_no": paragraph_no_on_page,
                        "paragraph_no_in_doc": paragraph_no_in_doc,
                        "text": paragraph_text,
                        "line_start": paragraph_line_start,
                        "line_end": current_line_no,
                    }
                )
                paragraph_no_on_page += 1
                paragraph_no_in_doc += 1
            paragraph_lines = []
            paragraph_line_start = None

        for local_index, line in enumerate(page_lines, start=1):
            if line.strip():
                if paragraph_line_start is None:
                    paragraph_line_start = global_line_number
                paragraph_lines.append(line)
            else:
                flush_paragraph(global_line_number - 1)
            global_line_number += 1

        flush_paragraph(global_line_number - 1)

        pages.append(
            {
                **page_reference,
                "text": page_text.strip(),
                "paragraphs": paragraphs,
            }
        )
        if page_index < len(page_texts):
            global_line_number += 1

    return {
        "schema_version": 1,
        "source_filename": source_filename,
        "title": title,
        "parser_name": parser_name,
        "hints": hints,
        "full_text": normalized_text,
        "pages": pages,
    }


def save_structured_document(directory: Path, source_filename: str, payload: dict[str, Any]) -> Path:
    """Persist a structured JSON document inside a directory."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / derive_structured_filename(source_filename)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_structured_document(path: Path) -> dict[str, Any] | None:
    """Load a structured JSON document if it exists and is valid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
