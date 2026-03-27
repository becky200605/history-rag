"""Helpers for book-level metadata generation, prompting, and persistence.

This module is intentionally router-agnostic. It prepares structured OCR output
for an AI metadata pass, normalizes the expected response shape, and persists the
result to disk for later catalog integration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

BOOK_METADATA_SCHEMA_VERSION = 1
DEFAULT_FRONT_PAGE_LIMIT = 10
DEFAULT_BODY_SAMPLE_COUNT = 3
DEFAULT_MAX_EXCERPT_CHARS = 1200
BOOK_METADATA_FILENAME_SUFFIX = ".book-metadata.json"
BOOK_METADATA_SUBDIR = ".book-metadata"
BOOK_TYPES = {"core", "specialized", "reference", "unknown"}


class MetadataField(BaseModel):
    """Single metadata value with confidence and evidence."""

    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None

    model_config = ConfigDict(extra="ignore")


class BookMetadataSamplePage(BaseModel):
    """One sampled page excerpt selected for metadata generation."""

    page_no: int
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    reasons: list[str] = Field(default_factory=list)
    text: str

    model_config = ConfigDict(extra="ignore")


class BookMetadataPromptInput(BaseModel):
    """Structured input passed to the metadata-generation AI."""

    source_filename: str
    title: str
    page_count: int
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    selected_pages: list[BookMetadataSamplePage] = Field(default_factory=list)
    selection_notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class BookMetadataSuggestion(BaseModel):
    """Expected AI output for routing and retrieval metadata."""

    title: str | None = None
    author: MetadataField | None = None
    type: MetadataField | None = None
    categories: list[MetadataField] = Field(default_factory=list)
    eras: list[MetadataField] = Field(default_factory=list)
    regions: list[MetadataField] = Field(default_factory=list)
    keywords: list[MetadataField] = Field(default_factory=list)
    summary: MetadataField | None = None
    ocr_quality: MetadataField | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="ignore")


class BookMetadataRecord(BaseModel):
    """Persisted analysis record containing prompt input and AI output."""

    schema_version: int = BOOK_METADATA_SCHEMA_VERSION
    source_filename: str
    source_title: str
    page_count: int
    prompt_input: BookMetadataPromptInput
    suggestion: BookMetadataSuggestion | None = None
    model_name: str | None = None
    generated_at: str | None = None

    model_config = ConfigDict(extra="ignore", protected_namespaces=())


class BookMetadataPromptBundle(BaseModel):
    """Prompt text and structured input for downstream AI execution."""

    system_prompt: str
    user_prompt: str
    prompt_input: BookMetadataPromptInput

    model_config = ConfigDict(extra="ignore")


def _coerce_metadata_field(value: Any) -> MetadataField | None:
    if value is None:
        return None
    if isinstance(value, MetadataField):
        return value
    if isinstance(value, Mapping):
        return MetadataField.model_validate(value)

    normalized = str(value).strip()
    if not normalized:
        return None
    return MetadataField(
        value=normalized,
        confidence=0.5,
        evidence="coerced_from_scalar",
    )


def _coerce_book_type(value: Any) -> MetadataField | None:
    field = _coerce_metadata_field(value)
    if field is None:
        return None
    normalized = field.value.strip().lower()
    if normalized not in BOOK_TYPES:
        normalized = "unknown"
    field.value = normalized
    return field


def _coerce_metadata_fields(values: Any) -> list[MetadataField]:
    if values is None:
        return []
    if isinstance(values, list):
        coerced = [_coerce_metadata_field(item) for item in values]
        return [item for item in coerced if item is not None]

    item = _coerce_metadata_field(values)
    return [item] if item is not None else []


def _normalize_book_metadata_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["author"] = _coerce_metadata_field(payload.get("author"))
    normalized["type"] = _coerce_book_type(payload.get("type"))
    normalized["categories"] = _coerce_metadata_fields(payload.get("categories"))
    normalized["eras"] = _coerce_metadata_fields(payload.get("eras"))
    normalized["regions"] = _coerce_metadata_fields(payload.get("regions"))
    normalized["keywords"] = _coerce_metadata_fields(payload.get("keywords"))
    normalized["summary"] = _coerce_metadata_field(payload.get("summary"))
    normalized["ocr_quality"] = _coerce_metadata_field(payload.get("ocr_quality"))
    return normalized


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 3)].rstrip() + "..."


def _page_no(page: Mapping[str, Any], fallback: int) -> int:
    for key in ("page_no", "pdf_page_no", "book_page_no"):
        value = page.get(key)
        try:
            if value is not None:
                parsed = int(value)
                if parsed > 0:
                    return parsed
        except (TypeError, ValueError):
            continue
    return fallback


def _page_text(page: Mapping[str, Any]) -> str:
    return _normalize_text(str(page.get("text") or ""))


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_like_toc(page_text: str) -> bool:
    if not page_text:
        return False

    normalized = _normalize_text(page_text).lower()
    if any(keyword in normalized for keyword in ("目录", "contents", "table of contents")):
        return True

    lines = _split_lines(page_text)
    if len(lines) < 3:
        return False

    dotted_lines = 0
    numbered_lines = 0
    for line in lines:
        if "....." in line or "……" in line:
            dotted_lines += 1
        if line and line[-1].isdigit():
            numbered_lines += 1

    if dotted_lines >= 2:
        return True
    return numbered_lines >= 3


def _evenly_spaced_indices(total: int, count: int) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    if count >= total:
        return list(range(total))

    step = total / (count + 1)
    indices: list[int] = []
    for index in range(1, count + 1):
        candidate = int(round(step * index)) - 1
        candidate = max(0, min(total - 1, candidate))
        if candidate not in indices:
            indices.append(candidate)
    return indices


def _dedupe_reasons(existing: list[str], new_reasons: list[str]) -> list[str]:
    seen = set(existing)
    merged = list(existing)
    for reason in new_reasons:
        if reason in seen:
            continue
        seen.add(reason)
        merged.append(reason)
    return merged


def extract_book_metadata_pages(
    structured_payload: Mapping[str, Any],
    *,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> list[BookMetadataSamplePage]:
    """Select only the first N pages for metadata generation."""
    pages = list(structured_payload.get("pages") or [])
    if not pages:
        return []

    front_count = min(front_page_limit, len(pages))
    selected_pages: list[BookMetadataSamplePage] = []

    for index, page in enumerate(pages[:front_count], start=1):
        page_no = _page_no(page, index)
        text = _truncate_text(_page_text(page), max_excerpt_chars)
        selected_pages.append(
            BookMetadataSamplePage(
                page_no=page_no,
                pdf_page_no=page.get("pdf_page_no"),
                book_page_no=page.get("book_page_no"),
                reasons=["front_page"],
                text=text,
            )
        )

    return selected_pages


def build_book_metadata_prompt_input(
    structured_payload: Mapping[str, Any],
    *,
    source_filename: str | None = None,
    title: str | None = None,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> BookMetadataPromptInput:
    """Convert structured OCR output into a compact AI prompt input."""
    selected_pages = extract_book_metadata_pages(
        structured_payload,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
    )

    inferred_source_filename = source_filename or str(structured_payload.get("source_filename") or "unknown")
    inferred_title = title or str(structured_payload.get("title") or inferred_source_filename)
    page_count = len(list(structured_payload.get("pages") or []))
    notes = [
        f"Selected the first {front_page_limit} pages as the front-page window.",
        "No TOC detection or body-page sampling is applied.",
    ]

    return BookMetadataPromptInput(
        source_filename=inferred_source_filename,
        title=inferred_title,
        page_count=page_count,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
        selected_pages=selected_pages,
        selection_notes=notes,
    )


def build_book_metadata_system_prompt() -> str:
    """Return the system prompt for a metadata classification run."""
    return (
        "You are classifying a book for retrieval routing.\n"
        "Use only the supplied excerpts and their page numbers.\n"
        "Do not invent facts, and do not use outside knowledge to fill gaps.\n"
        "The field `type` is only for retrieval routing and must be one of: core, specialized, reference, unknown.\n"
        "Do not use author-role words like 著, 编, 译 as `type`.\n"
        "Return valid JSON that matches the expected book-metadata schema.\n"
        "If a field is unknown, use null, an empty array, or 'unknown' as appropriate.\n"
        "Keep confidence scores between 0 and 1.\n"
        "Return JSON with these fields: title, author, type, categories, eras, regions, keywords, summary, ocr_quality, notes.\n"
    )


def render_book_metadata_user_prompt(prompt_input: BookMetadataPromptInput) -> str:
    """Render a human-readable prompt for an external model."""
    lines = [
        f"Title: {prompt_input.title}",
    ]
    for page in prompt_input.selected_pages:
        lines.extend(
            [
                "",
                f"### Page {page.page_no}",
                page.text or "",
            ]
        )
    return "\n".join(lines)


def build_book_metadata_prompt_bundle(
    structured_payload: Mapping[str, Any],
    *,
    source_filename: str | None = None,
    title: str | None = None,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> BookMetadataPromptBundle:
    """Build the system/user prompt pair and structured input for an AI pass."""
    prompt_input = build_book_metadata_prompt_input(
        structured_payload,
        source_filename=source_filename,
        title=title,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
    )
    return BookMetadataPromptBundle(
        system_prompt=build_book_metadata_system_prompt(),
        user_prompt=render_book_metadata_user_prompt(prompt_input),
        prompt_input=prompt_input,
    )


def parse_book_metadata_suggestion(payload: Mapping[str, Any] | str) -> BookMetadataSuggestion:
    """Parse and normalize a metadata response from an AI model."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping):
        raise TypeError("Book metadata payload must be a mapping or JSON string")
    return BookMetadataSuggestion.model_validate(_normalize_book_metadata_payload(payload))


def build_book_metadata_record(
    *,
    source_filename: str,
    source_title: str,
    page_count: int,
    prompt_input: BookMetadataPromptInput,
    suggestion: BookMetadataSuggestion | Mapping[str, Any] | str | None = None,
    model_name: str | None = None,
    generated_at: str | None = None,
) -> BookMetadataRecord:
    """Build a persisted analysis record from a prompt input and AI output."""
    parsed_suggestion: BookMetadataSuggestion | None = None
    if suggestion is not None:
        parsed_suggestion = (
            suggestion
            if isinstance(suggestion, BookMetadataSuggestion)
            else parse_book_metadata_suggestion(suggestion)
        )

    return BookMetadataRecord(
        source_filename=source_filename,
        source_title=source_title,
        page_count=page_count,
        prompt_input=prompt_input,
        suggestion=parsed_suggestion,
        model_name=model_name,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )


def derive_book_metadata_filename(source_filename: str) -> str:
    """Derive a stable metadata filename from the source filename."""
    return f"{source_filename}{BOOK_METADATA_FILENAME_SUFFIX}"


def get_book_metadata_dir(directory: Path) -> Path:
    """Return the dedicated subdirectory used for book-metadata sidecars."""
    return directory / BOOK_METADATA_SUBDIR


def save_book_metadata(
    directory: Path,
    source_filename: str,
    record: BookMetadataRecord | Mapping[str, Any],
) -> Path:
    """Persist a metadata record as JSON."""
    metadata_dir = get_book_metadata_dir(directory)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    path = metadata_dir / derive_book_metadata_filename(source_filename)
    payload = (
        record.model_dump(mode="json")
        if isinstance(record, BookMetadataRecord)
        else BookMetadataRecord.model_validate(record).model_dump(mode="json")
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_book_metadata(path: Path) -> BookMetadataRecord | None:
    """Load a persisted metadata record from disk."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return BookMetadataRecord.model_validate(payload)
    except Exception:
        return None


def load_book_metadata_for_source(directory: Path, source_filename: str) -> BookMetadataRecord | None:
    """Load a persisted metadata record for a given source filename."""
    return load_book_metadata(get_book_metadata_dir(directory) / derive_book_metadata_filename(source_filename))
