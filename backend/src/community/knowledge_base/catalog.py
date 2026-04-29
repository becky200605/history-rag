"""Book-level catalog and lightweight retrieval for knowledge docs."""

import json
import logging
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.community.knowledge_base.book_metadata import (
    BOOK_METADATA_FILENAME_SUFFIX,
    get_book_metadata_dir,
    load_book_metadata,
    normalize_folder_path,
    resolve_book_folder,
)
from src.community.knowledge_base.common import (
    derive_global_doc_id,
    derive_thread_doc_id,
    derive_user_doc_id,
    extract_title_from_text,
    normalize_search_text,
    resolve_project_path,
    tokenize_search_text,
)
from src.community.knowledge_base.ingestion import list_ingestion_records
from src.community.knowledge_base.structured_document import load_structured_document
from src.community.knowledge_base.user_store import list_user_records
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

logger = logging.getLogger(__name__)

BOOK_METADATA_FILENAMES = (".book_metadata.jsonl", ".book_metadata.json")
UNFILED_FOLDER_NAME = "未分类"

CORE_TYPE = "core"
SPECIALIZED_TYPE = "specialized"
REFERENCE_TYPE = "reference"
BOOK_LAYER_ORDER = ("user", "thread", CORE_TYPE, SPECIALIZED_TYPE, REFERENCE_TYPE, "unknown")
BOOK_LAYER_MINIMA = {
    "user": 3,
    "thread": 2,
    CORE_TYPE: 3,
    SPECIALIZED_TYPE: 4,
    REFERENCE_TYPE: 3,
    "unknown": 2,
}

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
    folder_path: str | None = None
    language_hint: str | None = None


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
    folder_path: str | None = None
    language_hint: str | None = None


TREE_FILE_KEY = "__files__"
TREE_SCOPE_ROOTS = {
    "user": ("用户书籍",),
    "thread": ("当前线程书籍",),
    CORE_TYPE: ("系统知识库", "核心通用书"),
    SPECIALIZED_TYPE: ("系统知识库", "专题支撑书"),
    REFERENCE_TYPE: ("系统知识库", "补充材料 / 参考工具书"),
    "unknown": ("系统知识库", "其他资料"),
}


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
        folder_path=normalize_folder_path(payload.get("folder")),
        language_hint=str(payload.get("language_hint") or "").strip() or None,
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
        folder_path=record.folder_path or existing.folder_path,
        language_hint=record.language_hint or existing.language_hint,
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
            folder_path=resolve_book_folder(suggestion),
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
        metadata.folder_path or "",
        metadata.language_hint or "",
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

    resolved_folder_path = metadata.folder_path or entry.folder_path
    metadata_text = _book_metadata_search_text(metadata)
    search_text = normalize_search_text(
        " ".join(part for part in [entry.search_text, resolved_folder_path or "", metadata_text] if part)
    )
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
        folder_path=resolved_folder_path,
        language_hint=metadata.language_hint or entry.language_hint,
    )


def _format_metadata_text(entry: BookCatalogEntry) -> str:
    parts: list[str] = []
    if entry.type and entry.type != "unknown":
        parts.append(f"类型: {entry.type}")
    if entry.folder_path:
        parts.append(f"目录: {entry.folder_path}")
    if entry.language_hint:
        parts.append(f"语言: {entry.language_hint}")
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
    if entry.scope == "user":
        return 0.9 if _is_broad_query(query) else 1.1
    if entry.scope == "thread":
        return 0.75 if _is_broad_query(query) else 0.95
    if book_type == "unknown":
        return 0.15

    broad = _is_broad_query(query)
    specific = _is_specific_query(query)
    if broad and book_type == CORE_TYPE:
        return 0.95
    if broad and book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 0.75
    if specific and book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 1.0
    if specific and book_type == CORE_TYPE:
        return 0.2
    if book_type == CORE_TYPE:
        return 0.45
    if book_type in {SPECIALIZED_TYPE, REFERENCE_TYPE}:
        return 0.6
    return 0.0


def _result_layer(entry: BookCatalogEntry) -> str:
    if entry.scope == "user":
        return "user"
    if entry.scope == "thread":
        return "thread"
    normalized = _normalize_type(entry.type)
    return normalized if normalized != "unknown" else "unknown"


def _expand_book_catalog_results(
    scored_entries: list[BookCatalogEntry],
    *,
    top_k: int,
) -> list[BookCatalogEntry]:
    if not scored_entries:
        return []

    limit = max(top_k, sum(BOOK_LAYER_MINIMA.values()))
    selected: list[BookCatalogEntry] = []
    selected_ids: set[str] = set()

    for entry in scored_entries[:top_k]:
        if entry.doc_id in selected_ids:
            continue
        selected.append(entry)
        selected_ids.add(entry.doc_id)

    for layer in BOOK_LAYER_ORDER:
        minimum = BOOK_LAYER_MINIMA.get(layer, 0)
        if minimum <= 0:
            continue
        already_selected = sum(1 for entry in selected if _result_layer(entry) == layer)
        if already_selected >= minimum:
            continue
        layer_candidates = [entry for entry in scored_entries if _result_layer(entry) == layer and entry.doc_id not in selected_ids]
        for entry in layer_candidates[: max(0, minimum - already_selected)]:
            if entry.doc_id in selected_ids:
                continue
            selected.append(entry)
            selected_ids.add(entry.doc_id)

    for entry in scored_entries:
        if len(selected) >= limit:
            break
        if entry.doc_id in selected_ids:
            continue
        selected.append(entry)
        selected_ids.add(entry.doc_id)

    return selected[:limit]


def _build_global_entries(
    docs_root: Path,
    metadata_index: dict[str, CatalogMetadataRecord],
    *,
    include_search_content: bool = True,
) -> list[BookCatalogEntry]:
    if not docs_root.exists():
        return []

    entries: list[BookCatalogEntry] = []
    seen_filenames: set[str] = set()
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
            preview = ""
            search_excerpt = ""
            if include_search_content:
                preview = _read_preview(preview_path)
                search_excerpt = _read_preview(preview_path, max_chars=3600)
                if not preview and payload.get("structured_path"):
                    preview = _read_structured_preview(Path(str(payload["structured_path"])))
                if not search_excerpt and payload.get("structured_path"):
                    search_excerpt = _read_structured_search_excerpt(Path(str(payload["structured_path"])))
            title = payload.get("display_title") or Path(str(source_filename)).stem
            extracted_title = extract_title_from_text(preview, title) if include_search_content else ""
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
                folder_path=normalize_folder_path(payload.get("folder_path")),
                language_hint=str((payload.get("hints") or {}).get("language_hint") or "").strip() or None,
            )
            entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))
            seen_filenames.add(str(source_filename))
            if preview_filename:
                seen_filenames.add(str(preview_filename))

    for path in sorted(docs_root.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in {".json", ".jsonl"}:
            continue
        if path.name in seen_filenames:
            continue

        preview = ""
        search_excerpt = ""
        if include_search_content:
            preview = _read_preview(path)
            search_excerpt = _read_preview(path, max_chars=3600)
            if not preview and path.suffix.lower() == ".structured" and path.name.endswith(".structured.json"):
                preview = _read_structured_preview(path)
            if not search_excerpt and path.suffix.lower() == ".structured" and path.name.endswith(".structured.json"):
                search_excerpt = _read_structured_search_excerpt(path)

        title = path.stem
        extracted_title = extract_title_from_text(preview, title) if include_search_content else ""
        entry = BookCatalogEntry(
            doc_id=derive_global_doc_id(docs_root, path),
            title=title,
            filename=path.name,
            scope="global",
            source_path=str(path),
            source_url=f"/api/knowledge/docs/{path.name}",
            original_url=None,
            preview=preview[:240],
            search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
        )
        entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))

    return entries


def _build_thread_entries(
    thread_id: str,
    metadata_index: dict[str, CatalogMetadataRecord],
    *,
    include_search_content: bool = True,
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

        preview = ""
        search_excerpt = ""
        if include_search_content:
            preview = _read_preview(preview_path) if preview_path.exists() else ""
            search_excerpt = _read_preview(preview_path, max_chars=3600) if preview_path.exists() else ""
            if not preview and structured_path:
                preview = _read_structured_preview(structured_path)
            if not search_excerpt and structured_path:
                search_excerpt = _read_structured_search_excerpt(structured_path)
        title = record.get("display_title") or Path(record.get("source_filename", target_filename)).stem
        extracted_title = extract_title_from_text(preview, title) if include_search_content else ""
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
            language_hint=str((record.get("hints") or {}).get("language_hint") or "").strip() or None,
        )
        entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))

    return entries


def _build_user_entries(
    user_id: str,
    metadata_index: dict[str, CatalogMetadataRecord],
    *,
    include_search_content: bool = True,
) -> list[BookCatalogEntry]:
    docs_dir = get_paths().user_knowledge_docs_dir(user_id)
    if not docs_dir.exists():
        return []

    entries: list[BookCatalogEntry] = []
    for record in list_user_records(user_id):
        if not record.get("retrieval_enabled") or not record.get("indexable"):
            continue

        record_id = str(record.get("id") or "")
        target_filename = str(record.get("index_target_filename") or "")
        source_filename = str(record.get("source_filename") or target_filename)
        if not record_id or not target_filename:
            continue

        preview_filename = record.get("preview_filename")
        preview_path = docs_dir / str(preview_filename or source_filename or target_filename)
        structured_path = Path(str(record.get("structured_path"))) if record.get("structured_path") else None
        if not preview_path.exists() and not structured_path:
            continue

        preview = ""
        search_excerpt = ""
        if include_search_content:
            preview = _read_preview(preview_path) if preview_path.exists() else ""
            search_excerpt = _read_preview(preview_path, max_chars=3600) if preview_path.exists() else ""
            if not preview and structured_path:
                preview = _read_structured_preview(structured_path)
            if not search_excerpt and structured_path:
                search_excerpt = _read_structured_search_excerpt(structured_path)

        title = record.get("display_title") or record.get("title") or Path(source_filename or target_filename).stem
        extracted_title = extract_title_from_text(preview, str(title)) if include_search_content else ""
        entry = BookCatalogEntry(
            doc_id=derive_user_doc_id(record_id),
            title=str(title),
            filename=source_filename or target_filename,
            scope="user",
            source_path=str(preview_path),
            source_url=str(record.get("preview_artifact_url") or record.get("source_artifact_url") or ""),
            original_url=str(record.get("source_artifact_url") or "") or None,
            preview=preview[:240],
            search_text=normalize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            search_tokens=tokenize_search_text(f"{title} {extracted_title} {search_excerpt}"),
            type="user",
            folder_path=normalize_folder_path(record.get("folder_path")),
            language_hint=str((record.get("hints") or {}).get("language_hint") or "").strip() or None,
        )
        entries.append(_apply_metadata_to_entry(entry, _lookup_metadata_for_entry(entry, metadata_index)))

    return entries


def list_book_catalog(
    thread_id: str | None = None,
    user_id: str | None = None,
    *,
    include_search_content: bool = True,
    caller: str | None = None,
) -> list[BookCatalogEntry]:
    """List user/global knowledge books plus optional current-thread uploads."""
    started_at = time.perf_counter()
    kb_config = get_knowledge_base_config()
    docs_root = resolve_project_path(kb_config.docs_path)
    metadata_index = _load_book_metadata_index(docs_root)
    entries = _build_global_entries(
        docs_root,
        metadata_index,
        include_search_content=include_search_content,
    )
    global_count = len(entries)
    user_count = 0
    thread_count = 0
    if user_id:
        user_metadata_index = _load_book_metadata_index(get_paths().user_knowledge_docs_dir(user_id))
        user_entries = _build_user_entries(
            user_id,
            user_metadata_index,
            include_search_content=include_search_content,
        )
        user_count = len(user_entries)
        entries = user_entries + entries
    if thread_id:
        thread_metadata_index = _load_book_metadata_index(get_paths().sandbox_uploads_dir(thread_id))
        thread_entries = _build_thread_entries(
            thread_id,
            thread_metadata_index,
            include_search_content=include_search_content,
        )
        thread_count = len(thread_entries)
        entries = thread_entries + entries
    logger.info(
        "Book catalog built: global=%s user=%s thread=%s total=%s thread_id=%s has_user=%s include_search_content=%s caller=%s elapsed_ms=%.1f",
        global_count,
        user_count,
        thread_count,
        len(entries),
        thread_id,
        bool(user_id),
        include_search_content,
        caller or "",
        (time.perf_counter() - started_at) * 1000,
    )
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
    folder_text = normalize_search_text(entry.folder_path or "")
    summary_text = normalize_search_text(entry.summary)

    if normalized_query and normalized_query == title_text:
        boost += 12.0
    elif normalized_query and normalized_query in title_text:
        boost += 8.0

    if normalized_query and normalized_query in filename_text:
        boost += 6.0
    if normalized_query and folder_text and normalized_query in folder_text:
        boost += 5.0

    for token in query_tokens:
        if token in title_text:
            boost += 1.5
        if token in filename_text:
            boost += 1.25
        if folder_text and token in folder_text:
            boost += 1.1
        if token in summary_text:
            boost += 0.6
    return boost


def filter_book_catalog_entries(
    entries: list[BookCatalogEntry],
    *,
    doc_ids: list[str] | None = None,
    scopes: list[str] | None = None,
    folder_paths: list[str] | None = None,
) -> list[BookCatalogEntry]:
    """Apply optional scope/doc filters to a catalog entry list."""
    filtered = entries
    if doc_ids:
        allowed_doc_ids = set(doc_ids)
        filtered = [entry for entry in filtered if entry.doc_id in allowed_doc_ids]
    if scopes:
        allowed_scopes = {scope.strip().lower() for scope in scopes if scope and scope.strip()}
        filtered = [entry for entry in filtered if entry.scope in allowed_scopes]
    if folder_paths:
        normalized_folder_paths = [
            normalized
            for raw_path in folder_paths
            if (normalized := normalize_folder_path(raw_path))
        ]
        if normalized_folder_paths:
            filtered = [
                entry
                for entry in filtered
                if _entry_matches_any_folder(entry, normalized_folder_paths)
            ]
    return filtered


def _entry_filter_folder_path(entry: BookCatalogEntry) -> str | None:
    normalized = normalize_folder_path(entry.folder_path)
    if normalized:
        return normalized

    relative_parent = normalize_folder_path(str(Path(entry.filename).parent))
    if relative_parent:
        return relative_parent
    return UNFILED_FOLDER_NAME


def _entry_matches_any_folder(entry: BookCatalogEntry, folder_paths: list[str]) -> bool:
    entry_folder_path = _entry_filter_folder_path(entry)
    if not entry_folder_path:
        return False
    return any(
        entry_folder_path == folder_path or entry_folder_path.startswith(f"{folder_path}/")
        for folder_path in folder_paths
    )


def _entry_tree_root(entry: BookCatalogEntry) -> tuple[str, ...]:
    if entry.scope == "user":
        return TREE_SCOPE_ROOTS["user"]
    if entry.scope == "thread":
        return TREE_SCOPE_ROOTS["thread"]
    return TREE_SCOPE_ROOTS.get(_normalize_type(entry.type), TREE_SCOPE_ROOTS["unknown"])


def _entry_folder_segments(entry: BookCatalogEntry) -> list[str]:
    normalized = _entry_filter_folder_path(entry)
    if normalized:
        return normalized.split("/")

    return [UNFILED_FOLDER_NAME]


def _entry_tree_leaf(entry: BookCatalogEntry) -> str:
    display_title = entry.title or Path(entry.filename).stem or entry.filename or entry.doc_id
    return f"{display_title} [doc_id={entry.doc_id}]"


def render_book_catalog_directory_tree(
    entries: list[BookCatalogEntry],
    *,
    include_scope_roots: bool = False,
) -> str | None:
    """Render visible catalog entries as a simple directory tree."""
    started_at = time.perf_counter()
    if not entries:
        return None

    tree: dict[str, object] = {}

    def _children(node: dict[str, object]) -> dict[str, object]:
        existing = node.get("children")
        if isinstance(existing, dict):
            return existing
        created: dict[str, object] = {}
        node["children"] = created
        return created

    def _files(node: dict[str, object]) -> list[str]:
        existing = node.get(TREE_FILE_KEY)
        if isinstance(existing, list):
            return existing
        created: list[str] = []
        node[TREE_FILE_KEY] = created
        return created

    ordered_entries = sorted(
        entries,
        key=lambda entry: (
            _entry_tree_root(entry) if include_scope_roots else (),
            _entry_folder_segments(entry),
            entry.title,
            entry.doc_id,
        ),
    )
    for entry in ordered_entries:
        node = tree
        root_segments = _entry_tree_root(entry) if include_scope_roots else ()
        for segment in [*root_segments, *_entry_folder_segments(entry)]:
            node = _children(node).setdefault(segment, {})  # type: ignore[assignment]
        leaf = _entry_tree_leaf(entry)
        node_files = _files(node)
        if leaf not in node_files:
            node_files.append(leaf)

    lines = ["."]

    def _render(node: dict[str, object], prefix: str = "") -> None:
        folder_items = sorted(
            ((name, child) for name, child in _children(node).items()),
            key=lambda item: item[0],
        )
        file_items = sorted(_files(node))
        entries_to_render: list[tuple[str, str, object | None]] = [
            ("folder", name, child) for name, child in folder_items
        ]
        entries_to_render.extend(("file", name, None) for name in file_items)

        for index, (entry_type, name, child) in enumerate(entries_to_render):
            is_last = index == len(entries_to_render) - 1
            branch = "`-- " if is_last else "|-- "
            suffix = "/" if entry_type == "folder" else ""
            lines.append(f"{prefix}{branch}{name}{suffix}")
            if entry_type == "folder" and isinstance(child, dict):
                _render(child, prefix + ("    " if is_last else "|   "))

    _render(tree)
    rendered = "\n".join(lines)
    logger.info(
        "Book catalog tree rendered: entries=%s include_scope_roots=%s lines=%s elapsed_ms=%.1f",
        len(entries),
        include_scope_roots,
        len(lines),
        (time.perf_counter() - started_at) * 1000,
    )
    return rendered


def search_book_catalog(
    query: str,
    thread_id: str | None = None,
    user_id: str | None = None,
    top_k: int = 8,
    doc_ids: list[str] | None = None,
    scopes: list[str] | None = None,
    folder_paths: list[str] | None = None,
    entries: list[BookCatalogEntry] | None = None,
) -> list[BookCatalogEntry]:
    """Return the most relevant candidate books for a query."""
    started_at = time.perf_counter()
    catalog_entries = filter_book_catalog_entries(
        entries
        if entries is not None
        else list_book_catalog(
            thread_id=thread_id,
            user_id=user_id,
            caller="catalog.search_book_catalog",
        ),
        doc_ids=doc_ids,
        scopes=scopes,
        folder_paths=folder_paths,
    )
    tokens = tokenize_search_text(query)
    if not catalog_entries or not tokens:
        logger.info(
            "Book catalog search short-circuit: query=%r catalog_entries=%s token_count=%s elapsed_ms=%.1f",
            query,
            len(catalog_entries),
            len(tokens),
            (time.perf_counter() - started_at) * 1000,
        )
        return []

    doc_frequencies = _build_document_frequencies(catalog_entries)
    avg_doc_len = sum(max(1, len(entry.search_tokens)) for entry in catalog_entries) / len(catalog_entries)
    scored: list[tuple[float, BookCatalogEntry]] = []
    for entry in catalog_entries:
        score = _bm25_score(
            entry,
            query_tokens=tokens,
            doc_frequencies=doc_frequencies,
            corpus_size=len(catalog_entries),
            avg_doc_len=avg_doc_len,
        )
        score += _exact_match_boost(entry, query, tokens)
        score += _metadata_overlap_score(entry, tokens)
        score += _metadata_type_boost(entry, query)
        if score <= 0:
            normalized_query = normalize_search_text(query)
            search_text = normalize_search_text(entry.search_text)
            if normalized_query and any(token in search_text for token in tokens[:3]):
                score = 0.15
            elif _is_broad_query(query):
                score = 0.05
        scored.append((score, replace(entry, score=score)))

    scored.sort(key=lambda item: item[0], reverse=True)
    ordered = [entry for _, entry in scored]
    expanded = _expand_book_catalog_results(ordered, top_k=top_k)
    logger.info(
        "Book catalog search complete: query=%r catalog_entries=%s token_count=%s top_k=%s returned=%s elapsed_ms=%.1f",
        query,
        len(catalog_entries),
        len(tokens),
        top_k,
        len(expanded),
        (time.perf_counter() - started_at) * 1000,
    )
    return expanded
