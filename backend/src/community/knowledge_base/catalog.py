"""Book-level catalog and lightweight retrieval for knowledge docs."""

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.community.knowledge_base.book_metadata import (
    BOOK_METADATA_FILENAME_SUFFIX,
    get_book_metadata_dir,
    load_book_metadata,
)
from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    extract_title_from_text,
    normalize_search_text,
    resolve_project_path,
    tokenize_search_text,
)
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

BOOK_METADATA_FILENAMES = (".book_metadata.jsonl", ".book_metadata.json")

CORE_TYPE = "core"
SPECIALIZED_TYPE = "specialized"
REFERENCE_TYPE = "reference"

BROAD_QUERY_HINTS = (
    "通史",
    "概述",
    "总论",
    "综述",
    "发展",
    "演变",
    "历程",
    "全史",
    "整体",
    "宏观",
)

SPECIFIC_QUERY_HINTS = (
    "考证",
    "条文",
    "制度",
    "史料",
    "档案",
    "年表",
    "细节",
    "专题",
    "案例",
    "注释",
)


@dataclass
class BookCatalogEntry:
    doc_id: str
    title: str
    filename: str
    scope: str
    source_path: str
    source_url: str
    original_url: str | None
    preview: str
    search_text: str
    search_tokens: list[str]
    type: str = "unknown"
    categories: list[str] = field(default_factory=list)
    eras: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: str = ""
    priority: int | None = None
    score: float | None = None
    metadata_source: str | None = None


@dataclass
class CatalogMetadataRecord:
    doc_id: str | None = None
    source_filename: str | None = None
    title: str | None = None
    type: str = "unknown"
    categories: list[str] = field(default_factory=list)
    eras: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: str = ""
    priority: int | None = None
    search_terms: list[str] = field(default_factory=list)
    source_path: str | None = None


def _read_preview(path: Path, max_chars: int = 800) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except Exception:
        return ""


def _sample_search_excerpt(text: str, slice_size: int = 1200) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) <= slice_size * 2:
        return text[: slice_size * 2]

    midpoint = len(text) // 2
    start_mid = max(0, midpoint - slice_size // 2)
    end_mid = min(len(text), start_mid + slice_size)
    parts = [
        text[:slice_size],
        text[start_mid:end_mid],
        text[-slice_size:],
    ]
    return "\n".join(part for part in parts if part)


def _read_structured_preview(path: Path, max_chars: int = 800) -> str:
    payload = load_structured_document(path)
    if not payload:
        return ""
    full_text = str(payload.get("full_text", ""))
    return full_text[:max_chars]


def _read_structured_search_excerpt(path: Path, max_chars: int = 3600) -> str:
    payload = load_structured_document(path)
    if not payload:
        return ""
    full_text = str(payload.get("full_text", ""))
    excerpt = _sample_search_excerpt(full_text, slice_size=max_chars // 3)
    return excerpt[:max_chars]


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _as_optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_type(value: object) -> str:
    value = str(value or "").strip().lower()
    if value in {CORE_TYPE, SPECIALIZED_TYPE, REFERENCE_TYPE, "unknown"}:
        return value
    return "unknown"


def _field_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return str(getattr(value, "value", value) or "").strip()


def _read_json_payload(path: Path) -> list[dict[str, object]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []

    try:
        payload = json.loads(raw)
    except Exception:
        records: list[dict[str, object]] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                line_payload = json.loads(stripped)
            except Exception:
                continue
            if isinstance(line_payload, dict):
                records.append(line_payload)
        return records

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("books", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _coerce_catalog_metadata_record(payload: dict[str, object], source_path: str) -> CatalogMetadataRecord:
    return CatalogMetadataRecord(
        doc_id=str(payload.get("doc_id") or payload.get("docId") or "").strip() or None,
        source_filename=str(payload.get("source_filename") or payload.get("filename") or "").strip() or None,
        title=str(payload.get("title") or payload.get("book_title") or "").strip() or None,
        type=_normalize_type(payload.get("type")),
        categories=_as_list(payload.get("categories")),
        eras=_as_list(payload.get("eras")),
        regions=_as_list(payload.get("regions")),
        keywords=_as_list(payload.get("keywords")),
        summary=str(payload.get("summary") or payload.get("description") or "").strip(),
        priority=_as_optional_int(payload.get("priority")),
        search_terms=_as_list(payload.get("search_terms")),
        source_path=source_path,
    )


def _metadata_index_keys(record: CatalogMetadataRecord) -> list[str]:
    keys = [record.doc_id, record.source_filename, record.title]
    if record.source_filename:
        keys.append(Path(record.source_filename).name)
        keys.append(Path(record.source_filename).stem)
    return [key for key in keys if key]


def _merge_metadata_record(
    existing: CatalogMetadataRecord | None,
    record: CatalogMetadataRecord,
) -> CatalogMetadataRecord:
    if existing is None:
        return record
    return CatalogMetadataRecord(
        doc_id=record.doc_id or existing.doc_id,
        source_filename=record.source_filename or existing.source_filename,
        title=record.title or existing.title,
        type=record.type if record.type != "unknown" else existing.type,
        categories=record.categories or existing.categories,
        eras=record.eras or existing.eras,
        regions=record.regions or existing.regions,
        keywords=record.keywords or existing.keywords,
        summary=record.summary or existing.summary,
        priority=record.priority if record.priority is not None else existing.priority,
        search_terms=record.search_terms or existing.search_terms,
        source_path=record.source_path or existing.source_path,
    )


def _load_generated_book_metadata_index(directory: Path) -> dict[str, CatalogMetadataRecord]:
    metadata_index: dict[str, CatalogMetadataRecord] = {}
    metadata_dir = get_book_metadata_dir(directory)
    if not metadata_dir.exists():
        return metadata_index

    for path in sorted(metadata_dir.glob(f"*{BOOK_METADATA_FILENAME_SUFFIX}")):
        generated = load_book_metadata(path)
        if generated is None or generated.suggestion is None:
            continue
        suggestion = generated.suggestion
        summary = _field_value(suggestion.summary)
        record = CatalogMetadataRecord(
            source_filename=generated.source_filename,
            title=(suggestion.title or generated.source_title or "").strip() or None,
            type=_normalize_type(_field_value(suggestion.type)),
            categories=[value for value in (_field_value(item) for item in suggestion.categories) if value],
            eras=[value for value in (_field_value(item) for item in suggestion.eras) if value],
            regions=[value for value in (_field_value(item) for item in suggestion.regions) if value],
            keywords=[value for value in (_field_value(item) for item in suggestion.keywords) if value],
            summary=summary,
            search_terms=tokenize_search_text(summary),
            source_path=str(path),
        )
        for key in _metadata_index_keys(record):
            metadata_index[key] = _merge_metadata_record(metadata_index.get(key), record)
    return metadata_index


def _load_book_metadata_index(docs_root: Path) -> dict[str, CatalogMetadataRecord]:
    metadata_index: dict[str, CatalogMetadataRecord] = {}
    for rel_path in BOOK_METADATA_FILENAMES:
        path = docs_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        for payload in _read_json_payload(path):
            record = _coerce_catalog_metadata_record(payload, str(path))
            for key in _metadata_index_keys(record):
                metadata_index[key] = _merge_metadata_record(metadata_index.get(key), record)
    for key, record in _load_generated_book_metadata_index(docs_root).items():
        metadata_index[key] = _merge_metadata_record(metadata_index.get(key), record)
    return metadata_index


def _lookup_metadata_for_entry(
    entry: BookCatalogEntry,
    metadata_index: dict[str, CatalogMetadataRecord],
) -> CatalogMetadataRecord | None:
    candidates = [
        entry.doc_id,
        entry.filename,
        Path(entry.filename).name if entry.filename else None,
        Path(entry.filename).stem if entry.filename else None,
    ]
    for candidate in candidates:
        if candidate and candidate in metadata_index:
            return metadata_index[candidate]
    return None


def _book_metadata_search_text(metadata: CatalogMetadataRecord) -> str:
    parts = [
        metadata.type,
        metadata.title or "",
        metadata.summary,
        " ".join(metadata.categories),
        " ".join(metadata.eras),
        " ".join(metadata.regions),
        " ".join(metadata.keywords),
        " ".join(metadata.search_terms),
    ]
    return normalize_search_text(" ".join(part for part in parts if part))


def _apply_metadata_to_entry(
    entry: BookCatalogEntry,
    metadata: CatalogMetadataRecord | None,
) -> BookCatalogEntry:
    if metadata is None:
        return entry

    metadata_text = _book_metadata_search_text(metadata)
    search_text = normalize_search_text(" ".join(part for part in [entry.search_text, metadata_text] if part))
    return replace(
        entry,
        type=metadata.type if metadata.type else entry.type,
        categories=metadata.categories or entry.categories,
        eras=metadata.eras or entry.eras,
        regions=metadata.regions or entry.regions,
        keywords=metadata.keywords or entry.keywords,
        summary=metadata.summary or entry.summary,
        priority=metadata.priority if metadata.priority is not None else entry.priority,
        search_text=search_text,
        search_tokens=tokenize_search_text(search_text),
        metadata_source=metadata.source_path,
    )


def _format_metadata_text(entry: BookCatalogEntry) -> str:
    parts: list[str] = []
    if entry.type and entry.type != "unknown":
        parts.append(f"类型: {entry.type}")
    if entry.categories:
        parts.append(f"分类: {'、'.join(entry.categories)}")
    if entry.eras:
        parts.append(f"时代: {'、'.join(entry.eras)}")
    if entry.regions:
        parts.append(f"地区: {'、'.join(entry.regions)}")
    if entry.priority is not None:
        parts.append(f"优先级: {entry.priority}")
    if entry.summary:
        parts.append(f"摘要: {entry.summary}")
    return " | ".join(parts)


def _is_broad_query(query: str) -> bool:
    normalized = normalize_search_text(query)
    return any(hint in normalized for hint in BROAD_QUERY_HINTS)


def _is_specific_query(query: str) -> bool:
    normalized = normalize_search_text(query)
    return any(hint in normalized for hint in SPECIFIC_QUERY_HINTS)


def _metadata_overlap_score(entry: BookCatalogEntry, query_tokens: list[str]) -> float:
    metadata_terms = [
        entry.type,
        entry.summary,
        " ".join(entry.categories),
        " ".join(entry.eras),
        " ".join(entry.regions),
        " ".join(entry.keywords),
    ]
    metadata_tokens = set(tokenize_search_text(" ".join(part for part in metadata_terms if part)))
    if not metadata_tokens:
        return 0.0

    overlap = set(query_tokens) & metadata_tokens
    if not overlap:
        return 0.0
    return min(2.5, 0.5 * len(overlap))


def _metadata_type_boost(entry: BookCatalogEntry, query: str) -> float:
    book_type = _normalize_type(entry.type)
    if book_type == "unknown":
        return 0.0

    broad = _is_broad_query(query)
    specific = _is_specific_query(query)
    if broad and book_type == CORE_TYPE:
        return 1.2
    if broad and book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 0.35
    if specific and book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 1.0
    if specific and book_type == CORE_TYPE:
        return 0.2
    if book_type == CORE_TYPE:
        return 0.45
    if book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 0.6
    return 0.0


def _build_global_entries(
    docs_root: Path,
    metadata_index: dict[str, CatalogMetadataRecord],
) -> list[BookCatalogEntry]:
    if not docs_root.exists():
        return []

    entries: list[BookCatalogEntry] = []
    ingestion_dir = docs_root / ".ingestion"

    if ingestion_dir.exists():
        for path in sorted(ingestion_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("schema_version") == 1:
                continue

            source_filename = payload.get("source_filename")
            if not payload.get("indexable") or not source_filename:
                continue

            preview_filename = payload.get("preview_filename")
            preview_path = docs_root / str(preview_filename or source_filename)
            preview = _read_preview(preview_path)
            search_excerpt = _read_preview(preview_path, max_chars=3600)
            if not preview and payload.get("structured_path"):
                preview = _read_structured_preview(Path(str(payload["structured_path"])))
            if not search_excerpt and payload.get("structured_path"):
                search_excerpt = _read_structured_search_excerpt(Path(str(payload["structured_path"])))
            title = payload.get("display_title") or Path(str(source_filename)).stem
            extracted_title = extract_title_from_text(preview, title)
            entry = BookCatalogEntry(
                doc_id=derive_global_doc_id(docs_root, Path(str(source_filename))),
                title=title,
                filename=str(source_filename),
                scope="global",
                source_path=str(preview_path),
                source_url=payload.get("preview_artifact_url") or f"/api/knowledge/docs/{preview_path.name}",
                original_url=payload.get("source_artifact_url"),
                preview=preview[:240],
                search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
                search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            )
            entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))

    return entries


def _build_thread_entries(
    thread_id: str,
    metadata_index: dict[str, CatalogMetadataRecord],
) -> list[BookCatalogEntry]:
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    if not uploads_dir.exists():
        return []

    entries: list[BookCatalogEntry] = []
    for record in list_ingestion_records(thread_id):
        target_filename = record.get("index_target_filename")
        preview_filename = record.get("preview_filename")
        if not record.get("indexable") or not target_filename:
            continue
        preview_path = uploads_dir / str(preview_filename or record.get("source_filename") or target_filename)
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if not preview_path.exists() and not structured_path:
            continue

        preview = _read_preview(preview_path) if preview_path.exists() else ""
        search_excerpt = _read_preview(preview_path, max_chars=3600) if preview_path.exists() else ""
        if not preview and structured_path:
            preview = _read_structured_preview(structured_path)
        if not search_excerpt and structured_path:
            search_excerpt = _read_structured_search_excerpt(structured_path)
        title = record.get("display_title") or Path(record.get("source_filename", target_filename)).stem
        extracted_title = extract_title_from_text(preview, title)
        original_url = None
        source_filename = record.get("source_filename")
        if source_filename and source_filename != target_filename:
            original_url = record.get("source_artifact_url")

        entry = BookCatalogEntry(
            doc_id=derive_thread_doc_id(Path(source_filename or target_filename)),
            title=title,
            filename=source_filename or target_filename,
            scope="thread",
            source_path=str(preview_path),
            source_url=record.get("preview_artifact_url")
            or f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{preview_path.name}",
            original_url=original_url,
            preview=preview[:240],
            search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
        )
        entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))

    return entries


def list_book_catalog(thread_id: str | None = None) -> list[BookCatalogEntry]:
    """List global knowledge books plus optional current-thread uploads."""
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    metadata_index = _load_book_metadata_index(docs_root)
    entries = _build_global_entries(docs_root, metadata_index)
    if thread_id:
        thread_metadata_index = _load_book_metadata_index(get_paths().sandbox_uploads_dir(thread_id))
        entries = _build_thread_entries(thread_id, thread_metadata_index) + entries
    return entries


def _build_document_frequencies(entries: list[BookCatalogEntry]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for entry in entries:
        for token in set(entry.search_tokens):
            frequencies[token] = frequencies.get(token, 0) + 1
    return frequencies


def _bm25_score(
    entry: BookCatalogEntry,
    *,
    query_tokens: list[str],
    doc_frequencies: dict[str, int],
    corpus_size: int,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens:
        return 0.0

    score = 0.0
    token_counts: dict[str, int] = {}
    for token in entry.search_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1

    doc_len = max(1, len(entry.search_tokens))
    for token in query_tokens:
        tf = token_counts.get(token, 0)
        if tf == 0:
            continue
        df = doc_frequencies.get(token, 0)
        idf = math.log(1 + (corpus_size - df + 0.5) / (df + 0.5))
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1.0))
        score += idf * numerator / denominator
    return score


def _exact_match_boost(entry: BookCatalogEntry, query: str, query_tokens: list[str]) -> float:
    boost = 0.0
    normalized_query = normalize_search_text(query)
    title_text = normalize_search_text(entry.title)
    filename_text = normalize_search_text(entry.filename)
    summary_text = normalize_search_text(entry.summary)

    if normalized_query and normalized_query == title_text:
        boost += 12.0
    elif normalized_query and normalized_query in title_text:
        boost += 8.0

    if normalized_query and normalized_query in filename_text:
        boost += 6.0

    for token in query_tokens:
        if token in title_text:
            boost += 1.5
        if token in filename_text:
            boost += 1.25
        if token in summary_text:
            boost += 0.6
    return boost


def search_book_catalog(query: str, thread_id: str | None = None, top_k: int = 8) -> list[BookCatalogEntry]:
    """Return the most relevant candidate books for a query."""
    entries = list_book_catalog(thread_id)
    tokens = tokenize_search_text(query)
    if not entries or not tokens:
        return []

    doc_frequencies = _build_document_frequencies(entries)
    avg_doc_len = sum(max(1, len(entry.search_tokens)) for entry in entries) / len(entries)
    scored: list[tuple[float, BookCatalogEntry]] = []
    for entry in entries:
        score = _bm25_score(
            entry,
            query_tokens=tokens,
            doc_frequencies=doc_frequencies,
            corpus_size=len(entries),
            avg_doc_len=avg_doc_len,
        )
        score += _exact_match_boost(entry, query, tokens)
        score += _metadata_overlap_score(entry, tokens)
        score += _metadata_type_boost(entry, query)
        if score > 0:
            scored.append((score, replace(entry, score=score)))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]
