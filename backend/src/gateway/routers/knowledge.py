import json
import logging
import mimetypes
import threading
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.community.knowledge_base.book_metadata import (
    MetadataField,
    build_book_metadata_prompt_input,
    build_book_metadata_record,
    load_book_metadata_for_source,
    normalize_folder_path,
    resolve_book_folder,
    save_book_metadata,
)
from src.community.knowledge_base.book_metadata_runtime import (
    build_existing_folder_tree,
    generate_book_metadata_record,
    maybe_generate_book_metadata,
)
from src.community.knowledge_base.citations import (
    encode_source_url,
    resolve_result_citation_context,
)
from src.community.knowledge_base.common import resolve_project_path
from src.community.knowledge_base.document_parsers import OFFICE_EXTENSIONS, PDF_EXTENSIONS
from src.community.knowledge_base.folder_registry import (
    delete_folder_path,
    ensure_folder_path,
    ensure_folder_paths,
    list_folder_paths,
    rename_folder_path,
)
from src.community.knowledge_base.indexer import (
    _get_upsert_batch_size,
    delete_global_knowledge_documents,
    rebuild_global_knowledge_index,
    rebuild_thread_upload_index,
    upsert_global_knowledge_record,
    upsert_global_knowledge_records,
)
from src.community.knowledge_base.locator import extract_document_context, locate_document
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.community.knowledge_base.retriever import get_qdrant_client, get_retriever
from src.community.knowledge_base.structured_document import (
    build_bbox_from_position,
    build_structured_document,
    load_structured_document,
    save_structured_document,
)
from src.community.knowledge_base.translation_grpc import translate_blocks_to_chinese_via_grpc
from src.config.knowledge_base_config import get_knowledge_base_config
from src.community.knowledge_base.common import derive_global_doc_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge-base"])
logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024

INDEXABLE_EXTENSIONS = {".md", ".txt"}
_knowledge_operation_lock = threading.Lock()
_global_queue_condition = threading.Condition()
_global_ocr_queue: deque[str] = deque()
_global_embedding_queue: deque[str] = deque()
_global_queued_ocr: set[str] = set()
_global_queued_embedding: set[str] = set()
_global_ocr_worker: threading.Thread | None = None
_global_embedding_worker: threading.Thread | None = None


def _encode_url_path(url: str | None) -> str | None:
    return encode_source_url(url)


def _acquire_knowledge_operation_lock() -> None:
    if not _knowledge_operation_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Another knowledge-base operation is already in progress. Please wait for it to finish.",
        )


def _release_knowledge_operation_lock() -> None:
    if _knowledge_operation_lock.locked():
        _knowledge_operation_lock.release()


def _remove_global_queued_filename(filename: str) -> None:
    global _global_ocr_queue, _global_embedding_queue
    with _global_queue_condition:
        if filename in _global_queued_ocr:
            _global_queued_ocr.discard(filename)
            _global_ocr_queue = deque(item for item in _global_ocr_queue if item != filename)
        if filename in _global_queued_embedding:
            _global_queued_embedding.discard(filename)
            _global_embedding_queue = deque(item for item in _global_embedding_queue if item != filename)


def _enqueue_global_ocr(filename: str) -> None:
    with _global_queue_condition:
        if filename in _global_queued_ocr:
            return
        _global_queued_ocr.add(filename)
        _global_ocr_queue.append(filename)
        _global_queue_condition.notify_all()


def _enqueue_global_embedding(filename: str) -> None:
    with _global_queue_condition:
        if filename in _global_queued_embedding:
            return
        _global_queued_embedding.add(filename)
        _global_embedding_queue.append(filename)
        _global_queue_condition.notify_all()


def _recover_pending_global_jobs() -> None:
    for record in _list_global_records():
        filename = record.get("source_filename")
        if not filename or not record.get("indexable"):
            continue
        status = str(record.get("parse_status") or "")
        if status in {"queued", "queued_ocr", "pending_parse"}:
            _enqueue_global_ocr(str(filename))
            continue
        if status in {"parsed", "queued_embedding", "index_failed"}:
            _enqueue_global_embedding(str(filename))


def _ensure_global_queue_workers_started() -> None:
    global _global_ocr_worker, _global_embedding_worker
    started_worker = False
    with _global_queue_condition:
        if _global_ocr_worker is None or not _global_ocr_worker.is_alive():
            _global_ocr_worker = threading.Thread(
                target=_global_ocr_worker_loop,
                name="global-knowledge-ocr-worker",
                daemon=True,
            )
            _global_ocr_worker.start()
            started_worker = True
        if _global_embedding_worker is None or not _global_embedding_worker.is_alive():
            _global_embedding_worker = threading.Thread(
                target=_global_embedding_worker_loop,
                name="global-knowledge-embedding-worker",
                daemon=True,
                )
            _global_embedding_worker.start()
            started_worker = True
    if started_worker:
        _recover_pending_global_jobs()


def _current_global_queue_positions() -> tuple[dict[str, int], dict[str, int]]:
    with _global_queue_condition:
        ocr_positions = {filename: index + 1 for index, filename in enumerate(_global_ocr_queue)}
        embedding_positions = {filename: index + 1 for index, filename in enumerate(_global_embedding_queue)}
    return ocr_positions, embedding_positions


class KnowledgeBaseStatus(BaseModel):
    """Response model for knowledge base status."""
    enabled: bool
    doc_count: int
    collection_name: str
    docs_path: str


class ReindexResponse(BaseModel):
    """Response model for reindex operation."""
    status: str
    message: str


class SearchResult(BaseModel):
    """Response model for search result."""
    content: str
    score: float
    filename: str
    source: str
    line_start: int | None = None
    line_end: int | None = None
    page_no: int | None = None
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    paragraph_no: int | None = None
    bbox: dict[str, float] | None = None
    source_url: str | None = None
    original_url: str | None = None
    page: int | None = None
    source_type: str = "unknown"


class SearchResponse(BaseModel):
    """Response model for search operation."""
    query: str
    results: list[SearchResult]


class KnowledgeParagraphLocationResponse(BaseModel):
    doc_id: str | None = None
    scope: str | None = None
    filename: str
    title: str
    page_count: int | None = None
    page_no: int | None = None
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    paragraph_no: int | None = None
    bbox: dict[str, float] | None = None
    page_meta: dict[str, Any] | None = None
    text: str
    source_url: str | None = None
    original_url: str | None = None


class KnowledgeUploadResponse(BaseModel):
    """Response model for global knowledge upload operations."""

    success: bool
    files: list[dict[str, Any]]
    message: str


class UploadKnowledgeDocumentResponse(BaseModel):
    """Compatibility response model for settings-page uploads."""

    status: str
    message: str
    filename: str
    markdown_filename: str | None = None


class KnowledgeDocumentInfo(BaseModel):
    """Compatibility metadata model for settings-page document listing."""

    filename: str
    size: int
    modified: float
    extension: str


class KnowledgeDocumentListResponse(BaseModel):
    """Compatibility response model for settings-page document listing."""

    docs: list[KnowledgeDocumentInfo]


class KnowledgeMetadataUpdateRequest(BaseModel):
    type: str | None = None
    folder: str | None = None
    categories: list[str] | None = None
    eras: list[str] | None = None
    regions: list[str] | None = None
    keywords: list[str] | None = None
    summary: str | None = None
    language_hint: str | None = None
    layout_hint: str | None = None
    document_type_hint: str | None = None


class FolderMutationRequest(BaseModel):
    path: str
    new_path: str | None = None


class TranslationBlockRequest(BaseModel):
    key: str
    text: str


class TranslateBlocksRequest(BaseModel):
    paragraphs: list[TranslationBlockRequest]
    source_language_hint: str | None = None


def _build_structured_page_payload(document: Any, *, page_no: int | None, pdf_page_no: int | None) -> dict[str, Any] | None:
    for page in document.payload.get("pages") or []:
        current_page_no = int(page.get("page_no") or 0)
        current_pdf_page_no = int(page.get("pdf_page_no") or current_page_no)
        if page_no is not None and current_page_no != page_no:
            continue
        if pdf_page_no is not None and current_pdf_page_no != pdf_page_no:
            continue
        return {
            "doc_id": document.doc_id,
            "scope": document.scope,
            "filename": document.filename,
            "title": document.title,
            "layout_hint": (document.payload.get("hints") or {}).get("layout_hint"),
            "page_count": len(list(document.payload.get("pages") or [])),
            "page_no": page.get("page_no"),
            "pdf_page_no": page.get("pdf_page_no"),
            "book_page_no": page.get("book_page_no"),
            "page_number_source": page.get("page_number_source"),
            "page_meta": page.get("meta") or {},
            "paragraphs": [
                {
                    **paragraph,
                    "bbox": paragraph.get("bbox") or build_bbox_from_position(paragraph.get("position")),
                }
                for paragraph in page.get("paragraphs") or []
            ],
            "source_url": _encode_url_path(document.source_url),
            "original_url": _encode_url_path(document.original_url),
        }
    return None


async def save_upload_file(file: UploadFile, destination: Path, chunk_size: int = UPLOAD_CHUNK_SIZE) -> int:
    """Stream an uploaded file to disk and return its size in bytes."""
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as buffer:
        while chunk := await file.read(chunk_size):
            buffer.write(chunk)
            size += len(chunk)
    await file.close()
    return size


def get_global_docs_dir() -> Path:
    """Resolve and create the global knowledge docs directory."""
    docs_dir = resolve_project_path(get_knowledge_base_config().docs_path)
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


def get_global_ingestion_dir() -> Path:
    """Directory storing ingestion metadata for global uploads."""
    ingestion_dir = get_global_docs_dir() / ".ingestion"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    return ingestion_dir


def _global_folder_registry_path() -> Path:
    return get_global_docs_dir() / ".folders.json"


def _global_record_path(filename: str) -> Path:
    return get_global_ingestion_dir() / f"{filename}.json"


def _save_global_record(filename: str, record: dict[str, Any]) -> None:
    _global_record_path(filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_global_record(filename: str) -> dict[str, Any] | None:
    path = _global_record_path(filename)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_global_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(get_global_ingestion_dir().glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == 1:
                continue
            records.append(payload)
        except Exception:
            continue
    return records


def _build_global_record_lookup() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_source: dict[str, dict[str, Any]] = {}
    by_index_target: dict[str, dict[str, Any]] = {}
    for record in _list_global_records():
        source_filename = record.get("source_filename")
        if source_filename:
            by_source[source_filename] = record
        index_target_filename = record.get("index_target_filename")
        if index_target_filename:
            by_index_target[index_target_filename] = record
    return by_source, by_index_target


def _remove_global_record(filename: str) -> None:
    path = _global_record_path(filename)
    if path.exists():
        path.unlink()


def _find_global_record(filename: str) -> dict[str, Any] | None:
    record = _load_global_record(filename)
    if record:
        return record
    for candidate in _list_global_records():
        if candidate.get("index_target_filename") == filename:
            return candidate
    return None


def _build_global_urls(filename: str) -> dict[str, str]:
    return {
        "source_url": f"/api/knowledge/docs/{filename}",
    }


def _metadata_value(field: MetadataField | None) -> str | None:
    if field is None:
        return None
    value = str(field.value or "").strip()
    return value or None


def _metadata_values(fields: list[MetadataField] | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for field in fields or []:
        value = _metadata_value(field)
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _resolve_metadata_folder(
    suggestion: Any | None,
    *,
    fallback_tags: list[str] | None = None,
) -> str:
    folder = resolve_book_folder(suggestion)
    if folder:
        return folder
    for tag in fallback_tags or []:
        normalized = normalize_folder_path(tag)
        if normalized:
            return normalized
    return "未分类"


def _manual_metadata_field(value: str | None) -> MetadataField | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return MetadataField(value=normalized, confidence=1.0, evidence="manual_edit")


def _manual_metadata_fields(values: list[str] | None) -> list[MetadataField]:
    fields: list[MetadataField] = []
    seen: set[str] = set()
    for raw in values or []:
        normalized = str(raw or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        fields.append(MetadataField(value=normalized, confidence=1.0, evidence="manual_edit"))
    return fields


def _load_global_book_metadata(filename: str) -> dict[str, Any]:
    record = load_book_metadata_for_source(get_global_docs_dir(), filename)
    ingestion_record = _find_global_record(filename)
    suggestion = record.suggestion if record else None
    book_type = _metadata_value(suggestion.type) if suggestion else None
    categories = _metadata_values(suggestion.categories) if suggestion else []
    eras = _metadata_values(suggestion.eras) if suggestion else []
    regions = _metadata_values(suggestion.regions) if suggestion else []
    keywords = _metadata_values(suggestion.keywords) if suggestion else []
    summary = _metadata_value(suggestion.summary) if suggestion else None
    tags: list[str] = []
    for value in [*categories, *eras, *regions, *keywords]:
        if value and value not in tags:
            tags.append(value)
    folder = normalize_folder_path((ingestion_record or {}).get("folder_path")) or _resolve_metadata_folder(
        suggestion,
        fallback_tags=tags,
    )
    return {
        "type": book_type,
        "folder": folder,
        "categories": categories,
        "eras": eras,
        "regions": regions,
        "keywords": keywords,
        "summary": summary,
        "tags": tags,
        "language_hint": (ingestion_record or {}).get("hints", {}).get("language_hint"),
        "layout_hint": (ingestion_record or {}).get("hints", {}).get("layout_hint"),
        "document_type_hint": (ingestion_record or {}).get("hints", {}).get("document_type_hint"),
    }


def _list_global_folder_paths(files: list[dict[str, Any]] | None = None) -> list[str]:
    explicit_folders = list_folder_paths(_global_folder_registry_path())
    implicit_folders = [item.get("folder") for item in files or []]
    return ensure_folder_paths(_global_folder_registry_path(), [*explicit_folders, *implicit_folders])


def _load_structured_payload_for_metadata(filename: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Path]:
    record = _find_global_record(filename)
    docs_dir = get_global_docs_dir()
    file_path = docs_dir / filename

    if record is None and not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    structured_payload = None
    if record and record.get("structured_path"):
        structured_payload = load_structured_document(Path(str(record["structured_path"])))
    elif file_path.suffix.lower() in INDEXABLE_EXTENSIONS:
        structured_payload = build_structured_document(
            source_filename=filename,
            title=Path(filename).stem,
            text=file_path.read_text(encoding="utf-8"),
            parser_name="manual_metadata_edit",
            hints={},
        )

    return structured_payload, record, docs_dir


def _cleanup_global_record_artifacts(record: dict[str, Any], *, remove_source_file: bool) -> None:
    docs_dir = get_global_docs_dir()
    source_filename = record.get("source_filename")
    if remove_source_file and source_filename:
        source_path = docs_dir / str(source_filename)
        if source_path.exists():
            source_path.unlink()

    structured_path = record.get("structured_path")
    if structured_path:
        candidate = Path(str(structured_path))
        if candidate.exists():
            candidate.unlink()

    preview_filename = record.get("preview_filename")
    if preview_filename and preview_filename not in {record.get("source_filename"), record.get("index_target_filename")}:
        preview_path = docs_dir / str(preview_filename)
        if preview_path.exists():
            preview_path.unlink()


def _build_global_ingestion_record(
    filename: str,
    size: int,
    content_type: str | None,
    hints: dict[str, str],
    folder_path: str | None = None,
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    parse_method = "binary_only"
    indexable = False
    if suffix in INDEXABLE_EXTENSIONS or suffix in PDF_EXTENSIONS or suffix in OFFICE_EXTENSIONS:
        parse_method = "ocr_pdf_mineru_grpc"
        indexable = True

    urls = _build_global_urls(filename)
    return {
        "source_filename": filename,
        "display_title": Path(filename).stem,
        "source_extension": suffix,
        "source_size": size,
        "content_type": content_type,
        "parse_method": parse_method,
        "parse_status": "queued_ocr" if indexable else "uploaded",
        "indexable": indexable,
        "source_artifact_url": urls["source_url"],
        "preview_filename": filename if suffix in INDEXABLE_EXTENSIONS else None,
        "preview_artifact_url": urls["source_url"] if suffix in INDEXABLE_EXTENSIONS else None,
        "structured_filename": None,
        "structured_path": None,
        "structured_artifact_url": None,
        "index_target_filename": None,
        "index_target_path": None,
        "index_target_artifact_url": None,
        "index_target_format": None,
        "hints": hints,
        "folder_path": normalize_folder_path(folder_path),
        "error": None,
        "replace_existing_index": False,
        "embedding_checkpoint": None,
    }


def _mark_global_record_parsed(
    record: dict[str, Any],
    *,
    structured_filename: str,
    structured_path: str,
    preview_filename: str | None = None,
) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "queued_embedding",
            "structured_filename": structured_filename,
            "structured_path": structured_path,
            "structured_artifact_url": None,
            "index_target_filename": structured_filename,
            "index_target_path": structured_path,
            "index_target_artifact_url": None,
            "index_target_format": "structured_json",
            "error": None,
            "embedding_checkpoint": None,
        }
    )
    if preview_filename:
        record["preview_filename"] = preview_filename
        record["preview_artifact_url"] = _build_global_urls(preview_filename)["source_url"]
    return record


def _mark_global_record_failed(record: dict[str, Any], error: str) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "failed",
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "error": error,
            "embedding_checkpoint": None,
        }
    )
    return record


def _mark_global_record_pending(record: dict[str, Any], error: str) -> dict[str, Any]:
    record.update(
        {
            "parse_status": "pending_parse",
            "structured_filename": None,
            "structured_path": None,
            "structured_artifact_url": None,
            "index_target_filename": None,
            "index_target_path": None,
            "index_target_artifact_url": None,
            "index_target_format": None,
            "error": error,
            "embedding_checkpoint": None,
        }
    )
    return record


def _save_global_embedding_checkpoint(
    filename: str,
    *,
    next_chunk_index: int,
    total_chunks: int,
    content_fingerprint: str,
) -> None:
    record = _load_global_record(filename)
    if not record:
        return
    record["embedding_checkpoint"] = {
        "next_chunk_index": next_chunk_index,
        "total_chunks": total_chunks,
        "content_fingerprint": content_fingerprint,
        "batch_size": _get_upsert_batch_size(),
    }
    record["parse_status"] = "indexing"
    record["error"] = None
    _save_global_record(filename, record)


def _clear_global_embedding_checkpoint(record: dict[str, Any]) -> dict[str, Any]:
    record["embedding_checkpoint"] = None
    return record


def _mark_global_records_indexed(source_filenames: list[str] | None = None) -> None:
    allowed_filenames = {str(filename) for filename in source_filenames} if source_filenames else None
    for record in _list_global_records():
        source_filename = str(record.get("source_filename") or "")
        if allowed_filenames is not None and source_filename not in allowed_filenames:
            continue
        target_path = record.get("index_target_path")
        if not record.get("indexable") or not target_path:
            continue
        if not Path(str(target_path)).exists():
            continue
        record["parse_status"] = "indexed"
        record["error"] = None
        _clear_global_embedding_checkpoint(record)
        _save_global_record(record["source_filename"], record)


def _process_single_global_ocr(filename: str) -> None:
    docs_dir = get_global_docs_dir()
    ingestion_dir = get_global_ingestion_dir()
    metadata_config = get_knowledge_base_config().book_metadata
    record = _load_global_record(filename)
    if not record or not record.get("indexable"):
        return

    file_path = docs_dir / filename
    if not file_path.exists():
        record = _mark_global_record_failed(record, "source file missing")
        _save_global_record(filename, record)
        return

    record["parse_status"] = "parsing"
    record["error"] = None
    _save_global_record(filename, record)

    try:
        file_ext = file_path.suffix.lower()
        if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in INDEXABLE_EXTENSIONS:
            hints = record.get("hints") or {}
            record["parse_method"] = "ocr_pdf_mineru_grpc"
            _save_global_record(filename, record)
            structured_payload = build_structured_document_from_mineru_grpc(
                file_path,
                title=record["display_title"],
                parser_name=record["parse_method"],
                hints=hints,
                language_hint=hints.get("language_hint"),
            )
            structured_path = save_structured_document(
                ingestion_dir,
                filename,
                structured_payload,
            )
            maybe_generate_book_metadata(
                structured_payload=structured_payload,
                source_filename=filename,
                title=record["display_title"],
                output_dir=docs_dir,
                config=metadata_config,
            )
            record = _mark_global_record_parsed(
                record,
                structured_filename=structured_path.name,
                structured_path=str(structured_path),
                preview_filename=filename if file_ext in INDEXABLE_EXTENSIONS else None,
            )
        else:
            record["parse_status"] = "uploaded"

        _save_global_record(filename, record)
        if record.get("index_target_path"):
            _enqueue_global_embedding(filename)
    except Exception as exc:
        logger.exception("Failed to OCR/parse global upload %s: %s", filename, exc)
        record = _mark_global_record_failed(record, f"parse failed: {exc}")
        _save_global_record(filename, record)


def _process_single_global_embedding(filename: str) -> None:
    record = _load_global_record(filename)
    if not record or not record.get("index_target_path"):
        return

    record["parse_status"] = "indexing"
    record["error"] = None
    _save_global_record(filename, record)

    try:
        _acquire_knowledge_operation_lock()
    except HTTPException:
        record = _load_global_record(filename)
        if not record:
            return
        record["parse_status"] = "queued_embedding"
        record["error"] = None
        _save_global_record(filename, record)
        _enqueue_global_embedding(filename)
        return

    try:
        checkpoint = record.get("embedding_checkpoint")
        resume_chunk_index = 0
        expected_fingerprint = None
        if isinstance(checkpoint, dict):
            try:
                resume_chunk_index = int(checkpoint.get("next_chunk_index") or 0)
            except (TypeError, ValueError):
                resume_chunk_index = 0
            candidate_fingerprint = str(checkpoint.get("content_fingerprint") or "").strip()
            expected_fingerprint = candidate_fingerprint or None

        indexed_chunks, _fingerprint = upsert_global_knowledge_record(
            filename,
            resume_chunk_index=resume_chunk_index,
            expected_fingerprint=expected_fingerprint,
            on_batch_complete=lambda next_chunk_index, total_chunks, content_fingerprint: _save_global_embedding_checkpoint(
                filename,
                next_chunk_index=next_chunk_index,
                total_chunks=total_chunks,
                content_fingerprint=content_fingerprint,
            ),
        )
        if indexed_chunks <= 0:
            raise ValueError("No chunks were indexed into Qdrant")
        _mark_global_records_indexed([filename])
        logger.info("Background global knowledge reindex completed for %s", filename)
    except Exception as exc:
        logger.exception("Background global knowledge reindex failed for %s: %s", filename, exc)
        record = _load_global_record(filename)
        if not record:
            return
        record["parse_status"] = "index_failed"
        record["error"] = f"reindex failed: {exc}"
        _save_global_record(filename, record)
    finally:
        _release_knowledge_operation_lock()


def _global_ocr_worker_loop() -> None:
    while True:
        with _global_queue_condition:
            while not _global_ocr_queue:
                _global_queue_condition.wait()
            filename = _global_ocr_queue.popleft()
            _global_queued_ocr.discard(filename)
        _process_single_global_ocr(filename)


def _global_embedding_worker_loop() -> None:
    while True:
        with _global_queue_condition:
            while not _global_embedding_queue:
                _global_queue_condition.wait()
            filename = _global_embedding_queue.popleft()
            _global_queued_embedding.discard(filename)
        _process_single_global_embedding(filename)


def _process_global_knowledge_uploads(filenames: list[str]) -> None:
    """Parse uploaded global knowledge files and rebuild the index in the background."""
    try:
        docs_dir = get_global_docs_dir()
        ingestion_dir = get_global_ingestion_dir()
        metadata_config = get_knowledge_base_config().book_metadata
        needs_reindex = False
        force_reindex = False
        parsed_filenames: list[str] = []

        for safe_filename in filenames:
            record = _load_global_record(safe_filename)
            if not record:
                logger.warning("Global ingestion record missing for %s", safe_filename)
                continue

            file_path = docs_dir / safe_filename
            if not file_path.exists():
                record = _mark_global_record_failed(record, "source file missing")
                _save_global_record(safe_filename, record)
                continue

            record["parse_status"] = "parsing"
            record["error"] = None
            force_reindex = force_reindex or bool(record.get("replace_existing_index"))
            _save_global_record(safe_filename, record)

            try:
                file_ext = file_path.suffix.lower()
                if file_ext in PDF_EXTENSIONS or file_ext in OFFICE_EXTENSIONS or file_ext in INDEXABLE_EXTENSIONS:
                    hints = record.get("hints") or {}
                    record["parse_method"] = "ocr_pdf_mineru_grpc"
                    _save_global_record(safe_filename, record)
                    structured_payload = build_structured_document_from_mineru_grpc(
                        file_path,
                        title=record["display_title"],
                        parser_name=record["parse_method"],
                        hints=hints,
                        language_hint=hints.get("language_hint"),
                    )
                    structured_path = save_structured_document(
                        ingestion_dir,
                        safe_filename,
                        structured_payload,
                    )
                    maybe_generate_book_metadata(
                        structured_payload=structured_payload,
                        source_filename=safe_filename,
                        title=record["display_title"],
                        output_dir=docs_dir,
                        config=metadata_config,
                    )
                    record = _mark_global_record_parsed(
                        record,
                        structured_filename=structured_path.name,
                        structured_path=str(structured_path),
                        preview_filename=safe_filename if file_ext in INDEXABLE_EXTENSIONS else None,
                    )
                    needs_reindex = True
                    parsed_filenames.append(safe_filename)
                else:
                    record["parse_status"] = "uploaded"
            except Exception as exc:
                logger.exception("Failed to parse global upload %s: %s", safe_filename, exc)
                record = _mark_global_record_failed(record, f"parse failed: {exc}")

            _save_global_record(safe_filename, record)

        if not needs_reindex and not force_reindex:
            return

        for safe_filename in parsed_filenames:
            record = _load_global_record(safe_filename)
            if not record or not record.get("index_target_path"):
                continue
            record["parse_status"] = "indexing"
            record["error"] = None
            _save_global_record(safe_filename, record)

        try:
            indexed_chunks = upsert_global_knowledge_records(parsed_filenames)
            if indexed_chunks <= 0:
                raise ValueError("No chunks were indexed into Qdrant")
            _mark_global_records_indexed(parsed_filenames)
            logger.info("Background global knowledge reindex completed for %s", parsed_filenames)
        except Exception as exc:
            logger.exception("Background global knowledge reindex failed: %s", exc)
            for safe_filename in parsed_filenames:
                record = _load_global_record(safe_filename)
                if not record:
                    continue
                record["parse_status"] = "index_failed"
                record["error"] = f"reindex failed: {exc}"
                _save_global_record(safe_filename, record)
    finally:
        _release_knowledge_operation_lock()


def _reindex_global_knowledge_in_background() -> None:
    """Rebuild the global knowledge index without blocking the request thread."""
    try:
        rebuild_global_knowledge_index()
        _mark_global_records_indexed()
        logger.info("Background global knowledge reindex completed")
    except Exception as exc:
        logger.exception("Background global knowledge reindex failed: %s", exc)
    finally:
        _release_knowledge_operation_lock()


@router.get("/status", response_model=KnowledgeBaseStatus, summary="Get Knowledge Base Status")
def get_status() -> KnowledgeBaseStatus:
    """Get the current status of the knowledge base."""
    config = get_knowledge_base_config()
    
    if not config.enabled:
        return KnowledgeBaseStatus(
            enabled=False,
            doc_count=0,
            collection_name=config.qdrant.collection_name,
            docs_path=config.docs_path
        )

    # Count vectors in Qdrant collection
    try:
        client = get_qdrant_client()
        collection_info = client.get_collection(config.qdrant.collection_name)
        doc_count = collection_info.points_count
    except Exception:
        doc_count = 0

    return KnowledgeBaseStatus(
        enabled=True,
        doc_count=doc_count,
        collection_name=config.qdrant.collection_name,
        docs_path=config.docs_path
    )


@router.post("/reindex", response_model=ReindexResponse, summary="Trigger Reindexing")
def reindex_knowledge_base(thread_id: str | None = None) -> ReindexResponse:
    """Trigger a full reindexing of the knowledge base documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    _acquire_knowledge_operation_lock()
    try:
        global_chunks = rebuild_global_knowledge_index()
        if thread_id:
            thread_chunks = rebuild_thread_upload_index(thread_id)
            message = f"Knowledge base reindexed successfully (global={global_chunks}, thread={thread_chunks})"
        else:
            message = f"Knowledge base reindexed successfully (global={global_chunks})"
        return ReindexResponse(status="success", message=message)
    except Exception as e:
        logger.exception("Failed to reindex knowledge base")
        raise HTTPException(status_code=500, detail=f"Failed to reindex: {str(e)}")
    finally:
        _release_knowledge_operation_lock()


@router.post("/uploads", response_model=KnowledgeUploadResponse, summary="Upload Global Knowledge Documents")
async def upload_global_knowledge_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    language_hint: str | None = Form(default=None),
    layout_hint: str | None = Form(default=None),
    document_type_hint: str | None = Form(default=None),
    folder_path: str | None = Form(default=None),
) -> KnowledgeUploadResponse:
    """Upload files into the global knowledge base and reindex them."""
    _ = background_tasks
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    docs_dir = get_global_docs_dir()
    uploaded_files: list[dict[str, Any]] = []
    queued_filenames: list[str] = []
    normalized_folder_path = normalize_folder_path(folder_path)
    if normalized_folder_path:
        ensure_folder_path(_global_folder_registry_path(), normalized_folder_path)
    hints = {
        key: value
        for key, value in {
            "language_hint": language_hint,
            "layout_hint": layout_hint,
            "document_type_hint": document_type_hint,
        }.items()
        if value
    }

    for file in files:
        if not file.filename:
            continue
        safe_filename = Path(file.filename).name
        if not safe_filename:
            continue

        try:
            file_path = docs_dir / safe_filename
            file_size = await save_upload_file(file, file_path)
            existing_record = _load_global_record(safe_filename)
            if existing_record:
                _cleanup_global_record_artifacts(existing_record, remove_source_file=False)
                _remove_global_record(safe_filename)
            _remove_global_queued_filename(safe_filename)

            record = _build_global_ingestion_record(
                filename=safe_filename,
                size=file_size,
                content_type=file.content_type,
                hints=hints,
                folder_path=normalized_folder_path,
            )
            if existing_record and existing_record.get("index_target_path"):
                record["replace_existing_index"] = True

            file_info: dict[str, Any] = {
                "filename": safe_filename,
                "size": file_size,
                "artifact_url": _build_global_urls(safe_filename)["source_url"],
                "parse_method": record["parse_method"],
                "parse_status": record["parse_status"],
                "indexable": record["indexable"],
                "preview_filename": record.get("preview_filename"),
                "preview_artifact_url": record.get("preview_artifact_url"),
                "structured_filename": record.get("structured_filename"),
                "structured_artifact_url": record.get("structured_artifact_url"),
                "index_target_filename": record.get("index_target_filename"),
                "index_target_artifact_url": record.get("index_target_artifact_url"),
                "hints": hints,
            }
            if normalized_folder_path:
                file_info["folder"] = normalized_folder_path

            _save_global_record(safe_filename, record)
            if normalized_folder_path:
                try:
                    await update_global_knowledge_metadata(
                        safe_filename,
                        KnowledgeMetadataUpdateRequest(folder=normalized_folder_path),
                    )
                except HTTPException:
                    pass
            uploaded_files.append(file_info)
            if record.get("indexable"):
                queued_filenames.append(safe_filename)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to upload {safe_filename}: {exc}")

    if queued_filenames:
        _ensure_global_queue_workers_started()
        for filename in queued_filenames:
            _enqueue_global_ocr(filename)

    return KnowledgeUploadResponse(
        success=True,
        files=uploaded_files,
        message=(
            f"Successfully uploaded {len(uploaded_files)} file(s); "
            "files are queued for OCR and embedding in the background"
        ),
    )
    


@router.get("/uploads/list", response_model=dict, summary="List Global Knowledge Uploads")
def list_global_knowledge_files() -> dict:
    """List files currently stored in the global knowledge directory."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    docs_dir = get_global_docs_dir()
    ocr_positions, embedding_positions = _current_global_queue_positions()
    source_records, target_records = _build_global_record_lookup()
    preview_filenames = {
        str(record.get("preview_filename"))
        for record in source_records.values()
        if record.get("preview_filename") and record.get("preview_filename") != record.get("source_filename")
    }

    files: list[dict[str, Any]] = []
    for file_path in sorted(docs_dir.iterdir()):
        if not file_path.is_file():
            continue
        if file_path.name.startswith("."):
            continue

        record = source_records.get(file_path.name)
        if target_records.get(file_path.name) and not record:
            continue
        if file_path.name in preview_filenames and not record:
            continue

        stat = file_path.stat()
        entry: dict[str, Any] = {
            "doc_id": derive_global_doc_id(docs_dir, file_path),
            "scope": "global",
            "filename": file_path.name,
            "size": stat.st_size,
            "extension": file_path.suffix,
            "modified": stat.st_mtime,
            "artifact_url": _build_global_urls(file_path.name)["source_url"],
        }
        entry.update(_load_global_book_metadata(file_path.name))
        if record:
            queue_position = None
            queue_stage = None
            if file_path.name in ocr_positions:
                queue_stage = "ocr"
                queue_position = ocr_positions[file_path.name]
            elif file_path.name in embedding_positions:
                queue_stage = "embedding"
                queue_position = embedding_positions[file_path.name]
            entry.update(
                {
                    "parse_method": record.get("parse_method"),
                    "parse_status": record.get("parse_status"),
                    "indexable": record.get("indexable", False),
                    "preview_filename": record.get("preview_filename"),
                    "preview_artifact_url": record.get("preview_artifact_url"),
                    "structured_filename": record.get("structured_filename"),
                    "structured_artifact_url": record.get("structured_artifact_url"),
                    "index_target_filename": record.get("index_target_filename"),
                    "index_target_artifact_url": record.get("index_target_artifact_url"),
                    "hints": record.get("hints", {}),
                    "error": record.get("error"),
                    "queue_stage": queue_stage,
                    "queue_position": queue_position,
                }
            )
        else:
            entry.update(
                {
                    "parse_method": "untracked",
                    "parse_status": "uploaded",
                    "indexable": False,
                    "preview_filename": None,
                    "preview_artifact_url": None,
                    "structured_filename": None,
                    "structured_artifact_url": None,
                    "index_target_filename": None,
                    "index_target_artifact_url": None,
                    "hints": {},
                    "error": None,
                }
            )
        files.append(entry)

    return {"files": files, "folders": _list_global_folder_paths(files), "count": len(files)}


@router.post("/folders", response_model=dict, summary="Create Global Knowledge Folder")
def create_global_knowledge_folder(payload: FolderMutationRequest) -> dict:
    try:
        folders = ensure_folder_path(_global_folder_registry_path(), payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "folders": folders,
        "path": normalize_folder_path(payload.path),
        "message": "Created global knowledge folder",
    }


@router.patch("/folders", response_model=dict, summary="Rename Global Knowledge Folder")
async def rename_global_knowledge_folder(payload: FolderMutationRequest) -> dict:
    normalized_old = normalize_folder_path(payload.path)
    normalized_new = normalize_folder_path(payload.new_path)
    if not normalized_old or not normalized_new:
        raise HTTPException(status_code=400, detail="Both path and new_path are required")

    current_files = list_global_knowledge_files().get("files", [])
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if current_folder == normalized_old or (
            current_folder and current_folder.startswith(f"{normalized_old}/")
        ):
            suffix = current_folder[len(normalized_old) :] if current_folder else ""
            filename = str(file_info.get("filename") or "")
            if not filename:
                continue
            updated_folder = f"{normalized_new}{suffix}"
            await update_global_knowledge_metadata(
                filename,
                KnowledgeMetadataUpdateRequest(folder=updated_folder),
            )

    try:
        folders = rename_folder_path(
            _global_folder_registry_path(),
            normalized_old,
            normalized_new,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "folders": folders,
        "path": normalized_new,
        "message": "Renamed global knowledge folder",
    }


@router.delete("/folders", response_model=dict, summary="Delete Global Knowledge Folder")
def delete_global_knowledge_folder(path: str = Query(..., description="Logical folder path to delete")) -> dict:
    normalized_path = normalize_folder_path(path)
    if not normalized_path:
        raise HTTPException(status_code=400, detail="path is required")

    current_files = list_global_knowledge_files().get("files", [])
    for file_info in current_files:
        current_folder = normalize_folder_path(file_info.get("folder"))
        if current_folder == normalized_path or (
            current_folder and current_folder.startswith(f"{normalized_path}/")
        ):
            raise HTTPException(status_code=400, detail="Folder is not empty")

    try:
        folders = delete_folder_path(_global_folder_registry_path(), normalized_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "folders": folders,
        "deleted_path": normalized_path,
        "message": "Deleted global knowledge folder",
    }


@router.patch("/uploads/{filename}/metadata", response_model=dict, summary="Update Global Knowledge Metadata")
async def update_global_knowledge_metadata(
    filename: str,
    payload: KnowledgeMetadataUpdateRequest,
) -> dict:
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    structured_payload, record, docs_dir = _load_structured_payload_for_metadata(filename)

    if structured_payload is None:
        raise HTTPException(status_code=400, detail="This file does not have editable structured metadata yet")

    existing = load_book_metadata_for_source(docs_dir, filename)
    existing_suggestion = existing.suggestion if existing else None
    provided_fields = payload.model_fields_set
    prompt_input = (
        existing.prompt_input
        if existing is not None
        else build_book_metadata_prompt_input(
            structured_payload,
            source_filename=filename,
            title=str((record or {}).get("display_title") or Path(filename).stem),
            front_page_limit=(config.book_metadata.front_page_limit if config.book_metadata else 10),
            max_excerpt_chars=(config.book_metadata.max_excerpt_chars if config.book_metadata else 1200),
            existing_folder_tree=build_existing_folder_tree(
                docs_dir,
                exclude_source_filename=filename,
                folder_registry_path=_global_folder_registry_path(),
            ),
        )
    )

    suggestion = {
        "title": str((existing_suggestion.title if existing_suggestion else None) or (record or {}).get("display_title") or Path(filename).stem),
        "author": existing_suggestion.author if existing_suggestion else None,
        "type": (
            _manual_metadata_field(payload.type)
            if "type" in provided_fields
            else (existing_suggestion.type if existing_suggestion else None)
        ),
        "folder": (
            _manual_metadata_field(normalize_folder_path(payload.folder))
            if "folder" in provided_fields
            else (existing_suggestion.folder if existing_suggestion else None)
        ),
        "categories": (
            _manual_metadata_fields(payload.categories)
            if "categories" in provided_fields
            else (existing_suggestion.categories if existing_suggestion else [])
        ),
        "eras": (
            _manual_metadata_fields(payload.eras)
            if "eras" in provided_fields
            else (existing_suggestion.eras if existing_suggestion else [])
        ),
        "regions": (
            _manual_metadata_fields(payload.regions)
            if "regions" in provided_fields
            else (existing_suggestion.regions if existing_suggestion else [])
        ),
        "keywords": (
            _manual_metadata_fields(payload.keywords)
            if "keywords" in provided_fields
            else (existing_suggestion.keywords if existing_suggestion else [])
        ),
        "summary": (
            _manual_metadata_field(payload.summary)
            if "summary" in provided_fields
            else (existing_suggestion.summary if existing_suggestion else None)
        ),
        "ocr_quality": existing_suggestion.ocr_quality if existing_suggestion else None,
        "notes": "manual_edit",
    }

    book_metadata_record = build_book_metadata_record(
        source_filename=filename,
        source_title=str((record or {}).get("display_title") or Path(filename).stem),
        page_count=len(list(structured_payload.get("pages") or [])),
        prompt_input=prompt_input,
        suggestion=suggestion,
        model_name=(existing.model_name if existing else (config.book_metadata.model_name if config.book_metadata else None)),
    )
    save_book_metadata(docs_dir, filename, book_metadata_record)
    if record is not None:
        next_hints = dict(record.get("hints") or {})
        if "folder" in provided_fields:
            record["folder_path"] = normalize_folder_path(payload.folder)
            if payload.folder:
                ensure_folder_path(_global_folder_registry_path(), payload.folder)
        if "language_hint" in provided_fields:
            if payload.language_hint:
                next_hints["language_hint"] = payload.language_hint
            else:
                next_hints.pop("language_hint", None)
        if "layout_hint" in provided_fields:
            if payload.layout_hint:
                next_hints["layout_hint"] = payload.layout_hint
            else:
                next_hints.pop("layout_hint", None)
        if "document_type_hint" in provided_fields:
            if payload.document_type_hint:
                next_hints["document_type_hint"] = payload.document_type_hint
            else:
                next_hints.pop("document_type_hint", None)
        record["hints"] = next_hints
        _save_global_record(filename, record)
    return {
        "success": True,
        "message": f"Updated metadata for {filename}",
        "metadata": _load_global_book_metadata(filename),
    }


@router.post("/uploads/{filename}/metadata/regenerate", response_model=dict, summary="Regenerate Global Knowledge Metadata")
async def regenerate_global_knowledge_metadata(filename: str) -> dict:
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if config.book_metadata is None or not config.book_metadata.enabled:
        raise HTTPException(status_code=400, detail="Book metadata generation is not enabled")

    structured_payload, record, docs_dir = _load_structured_payload_for_metadata(filename)
    if structured_payload is None:
        raise HTTPException(status_code=400, detail="This file does not have editable structured metadata yet")

    source_title = str((record or {}).get("display_title") or Path(filename).stem)
    try:
        generate_book_metadata_record(
            structured_payload=structured_payload,
            source_filename=filename,
            title=source_title,
            output_dir=docs_dir,
            config=config.book_metadata,
        )
    except Exception as exc:
        logger.exception("Failed to regenerate metadata for %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to regenerate metadata: {exc}")

    return {
        "success": True,
        "message": f"Regenerated metadata for {filename}",
        "metadata": _load_global_book_metadata(filename),
    }


@router.delete("/uploads/{filename}", response_model=dict, summary="Delete Global Knowledge Upload")
async def delete_global_knowledge_file(filename: str) -> dict:
    """Delete a file from the global knowledge directory and rebuild the global index."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    _remove_global_queued_filename(filename)
    _acquire_knowledge_operation_lock()
    docs_dir = get_global_docs_dir()
    file_path = docs_dir / filename
    record = _find_global_record(filename)

    try:
        if record:
            source_filename = record.get("source_filename")
            _cleanup_global_record_artifacts(record, remove_source_file=True)
            if source_filename:
                _remove_global_record(str(source_filename))
        elif file_path.exists():
            file_path.unlink()
        else:
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")

        delete_global_knowledge_documents([record.get("source_filename") or filename] if record else [filename])
        _mark_global_records_indexed()
        return {
            "success": True,
            "message": f"Deleted {filename} from global knowledge base and updated the index",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {exc}")
    finally:
        _release_knowledge_operation_lock()


@router.post("/uploads/{filename}/reindex", response_model=dict, summary="Retry Global Knowledge Indexing")
async def retry_global_knowledge_file(filename: str) -> dict:
    """Retry OCR or indexing for a single tracked global knowledge file."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    record = _find_global_record(filename)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    if not record.get("indexable"):
        raise HTTPException(status_code=400, detail="This file type does not support indexing")

    source_filename = str(record.get("source_filename") or filename)
    file_path = get_global_docs_dir() / source_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file missing: {source_filename}")

    current_status = str(record.get("parse_status") or "")
    if current_status in {"queued", "queued_ocr", "parsing", "queued_embedding", "indexing"}:
        raise HTTPException(status_code=409, detail="This file is already being processed")

    should_enqueue_embedding = bool(record.get("index_target_path")) and current_status in {
        "parsed",
        "index_failed",
        "indexed",
    }
    should_enqueue_ocr = current_status in {"failed", "uploaded", "pending_parse"} or not should_enqueue_embedding

    record["error"] = None
    if should_enqueue_embedding:
        record["parse_status"] = "queued_embedding"
        _save_global_record(source_filename, record)
        _ensure_global_queue_workers_started()
        _enqueue_global_embedding(source_filename)
        return {
            "success": True,
            "message": f"已重新加入入库队列：{source_filename}",
        }

    record["parse_status"] = "queued_ocr"
    _save_global_record(source_filename, record)
    _ensure_global_queue_workers_started()
    if should_enqueue_ocr:
        _enqueue_global_ocr(source_filename)
    return {
        "success": True,
        "message": f"已重新加入解析队列：{source_filename}",
    }


@router.get("/search", response_model=SearchResponse, summary="Search Knowledge Base")
def search_knowledge_base(
    q: str = Query(..., description="Search query"),
    thread_id: str | None = Query(default=None, description="Optional thread ID to include uploaded docs"),
    user_id: str | None = Query(default=None, description="Optional user ID to include personal knowledge docs"),
    doc_ids: str | None = Query(default=None, description="Optional comma-separated doc_ids to filter candidate books"),
    folder_path: list[str] | None = Query(default=None, description="Optional folder-path filters"),
) -> SearchResponse:
    """Search the knowledge base for relevant documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    try:
        retriever = get_retriever()
        parsed_doc_ids = [item.strip() for item in doc_ids.split(",") if item.strip()] if doc_ids else None
        parsed_folder_paths = [normalized for raw in (folder_path or []) if (normalized := normalize_folder_path(raw))]
        results = retriever.search(
            q,
            thread_id=thread_id,
            user_id=user_id,
            doc_ids=parsed_doc_ids,
            folder_paths=parsed_folder_paths or None,
        )

        search_results = []
        for res in results:
            metadata = res.get("metadata", {})
            citation_context = resolve_result_citation_context(
                res,
                thread_id=thread_id,
                user_id=user_id,
            )

            search_results.append(
                SearchResult(
                    content=res["content"],
                    score=res["score"],
                    filename=res["filename"],
                    source=res["source"],
                    line_start=metadata.get("line_start"),
                    line_end=metadata.get("line_end"),
                    page_no=metadata.get("page_no"),
                    pdf_page_no=metadata.get("pdf_page_no"),
                    book_page_no=metadata.get("book_page_no"),
                    paragraph_no=metadata.get("paragraph_no"),
                    bbox=metadata.get("bbox"),
                    source_url=citation_context["source_url"],
                    original_url=citation_context["original_url"],
                    page=res.get("page"),
                    source_type=res.get("source_type", "unknown"),
                )
            )

        return SearchResponse(query=q, results=search_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get(
    "/docs",
    response_model=KnowledgeDocumentListResponse,
    summary="List Knowledge Documents",
)
def list_knowledge_documents() -> KnowledgeDocumentListResponse:
    """List all visible files under the knowledge docs directory."""
    response = list_global_knowledge_files()
    docs = [
        KnowledgeDocumentInfo(
            filename=file_info["filename"],
            size=int(file_info["size"]),
            modified=float(file_info.get("modified") or 0),
            extension=str(file_info.get("extension") or ""),
        )
        for file_info in response.get("files", [])
    ]
    return KnowledgeDocumentListResponse(docs=docs)


@router.post(
    "/docs/upload",
    response_model=UploadKnowledgeDocumentResponse,
    summary="Upload Knowledge Document",
)
async def upload_knowledge_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Knowledge document"),
    reindex: bool = Query(
        True,
        description="Compatibility flag. Structured uploads always reindex in the background.",
    ),
) -> UploadKnowledgeDocumentResponse:
    """Compatibility wrapper for the settings-page upload flow."""
    _ = reindex
    upload_response = await upload_global_knowledge_files(
        background_tasks,
        [file],
    )
    uploaded = upload_response.files[0] if upload_response.files else {}
    return UploadKnowledgeDocumentResponse(
        status="success" if upload_response.success else "error",
        message=upload_response.message,
        filename=str(uploaded.get("filename") or file.filename or ""),
        markdown_filename=str(uploaded.get("preview_filename") or "") or None,
    )


@router.delete(
    "/docs/{filename}",
    response_model=dict,
    summary="Delete Knowledge Document",
)
async def delete_knowledge_document(
    filename: str,
) -> dict:
    """Compatibility wrapper for deleting a knowledge document."""
    return await delete_global_knowledge_file(filename)


@router.get("/docs/{filename}", summary="Get Knowledge Document")
def get_knowledge_document(
    filename: str,
    download: bool = False,
    page: int | None = Query(None, description="Page number for PDF files (0-based)"),
):
    """Get a knowledge document by filename.

    Supports URL-encoded names like 民国财政史_(杨荫溥).md.
    For PDF files, the page parameter can be used to indicate the target page
    (passed to frontend via X-Page header).
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = get_global_docs_dir()
    file_path = docs_root / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    # Ensure resolved path is under docs_root (path traversal protection)
    try:
        file_path = file_path.resolve()
        docs_root = docs_root.resolve()
        if not str(file_path).startswith(str(docs_root)):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except Exception:
        raise HTTPException(status_code=404, detail="Document not found")

    ext = Path(filename).suffix.lower()
    if download:
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type,
        )
    if ext == ".pdf":
        headers = {}
        if page is not None:
            headers["X-PDF-Page"] = str(page)
        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            headers=headers,
        )

    # Handle text/markdown files
    return FileResponse(
        path=file_path,
        media_type="text/markdown"
    )


@router.get(
    "/docs/{filename}/structured-page",
    response_model=dict,
    summary="Get structured page data for a knowledge document",
)
def get_knowledge_structured_page(
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if page_no is None and pdf_page_no is None:
        raise HTTPException(status_code=400, detail="page_no or pdf_page_no is required")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    payload = _build_structured_page_payload(document, page_no=page_no, pdf_page_no=pdf_page_no)
    if payload is not None:
        return payload

    raise HTTPException(status_code=404, detail="Structured page not found")


@router.post(
    "/docs/{filename}/translate-blocks",
    response_model=dict,
    summary="Translate structured page paragraphs into Chinese",
)
def translate_knowledge_blocks(
    filename: str,
    payload: TranslateBlocksRequest,
):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    blocks = [
        {
            "id": paragraph.key,
            "text": paragraph.text,
        }
        for paragraph in payload.paragraphs
        if paragraph.key.strip() and paragraph.text.strip()
    ]
    if not blocks:
        return {"translations": []}

    try:
        translations = translate_blocks_to_chinese_via_grpc(
            blocks,
            source_language_hint=payload.source_language_hint,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}") from exc

    return {
        "translations": [
            {
                "key": item["id"],
                "translation": item["translation"],
            }
            for item in translations
        ]
    }


@router.get(
    "/docs/{filename}/paragraph-location",
    response_model=KnowledgeParagraphLocationResponse,
    summary="Get paragraph location metadata for a knowledge document",
)
def get_knowledge_paragraph_location(
    filename: str,
    page_no: int | None = Query(default=None),
    pdf_page_no: int | None = Query(default=None),
    paragraph_no: int | None = Query(default=None),
):
    """Resolve page/paragraph metadata including bbox for a knowledge citation."""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if page_no is None and pdf_page_no is None and paragraph_no is None:
        raise HTTPException(status_code=400, detail="At least one of page_no, pdf_page_no, or paragraph_no is required")

    document = locate_document(thread_id=None, filename=filename)
    if not document:
        raise HTTPException(status_code=404, detail="Structured document not found")

    excerpts = extract_document_context(
        payload=document.payload,
        page_no=page_no,
        pdf_page_no=pdf_page_no,
        paragraph_no=paragraph_no,
        window=0,
    )
    if not excerpts:
        raise HTTPException(status_code=404, detail="Paragraph location not found")

    excerpt = excerpts[0]
    return KnowledgeParagraphLocationResponse(
        doc_id=document.doc_id,
        scope=document.scope,
        filename=document.filename,
        title=document.title,
        page_count=len(list(document.payload.get("pages") or [])),
        page_no=excerpt.get("page_no"),
        pdf_page_no=excerpt.get("pdf_page_no"),
        book_page_no=excerpt.get("book_page_no"),
        paragraph_no=excerpt.get("paragraph_no"),
        bbox=excerpt.get("bbox") or build_bbox_from_position(excerpt.get("position")),
        page_meta=excerpt.get("page_meta"),
        text=str(excerpt.get("text") or ""),
        source_url=_encode_url_path(document.source_url),
        original_url=_encode_url_path(document.original_url),
    )


@router.get("/docs/{filename}/page-image", summary="Render a PDF page image for citation viewing")
def get_knowledge_document_page_image(
    filename: str,
    pdf_page_no: int = Query(..., ge=1),
    dpi: int = Query(default=144, ge=72, le=300),
):
    """Render a physical PDF page to PNG for bbox-based citation highlighting."""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = get_global_docs_dir() / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Page images are only available for PDF documents")

    try:
        import fitz
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF rendering dependency unavailable: {exc}") from exc

    try:
        with fitz.open(file_path) as document:
            page_index = pdf_page_no - 1
            if page_index < 0 or page_index >= document.page_count:
                raise HTTPException(status_code=404, detail="PDF page not found")
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            png_bytes = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {exc}") from exc

    return Response(content=png_bytes, media_type="image/png")
