import logging
import json
import mimetypes
from pathlib import Path
import threading
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.community.knowledge_base.common import resolve_project_path
from src.community.knowledge_base.document_parsers import (
    OFFICE_EXTENSIONS,
    PDF_EXTENSIONS,
    extract_office_text_with_markitdown,
)
from src.community.knowledge_base.indexer import rebuild_global_knowledge_index, rebuild_thread_upload_index
from src.community.knowledge_base.locator import extract_document_context, locate_document
from src.community.knowledge_base.mineru_grpc import build_structured_document_from_mineru_grpc
from src.community.knowledge_base.structured_document import (
    build_structured_document,
    save_structured_document,
)
from src.community.knowledge_base.retriever import get_retriever, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge-base"])
logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024

INDEXABLE_EXTENSIONS = {".md", ".txt"}
_knowledge_operation_lock = threading.Lock()


def _encode_url_path(url: str | None) -> str | None:
    if not url:
        return url
    return quote(url, safe="/:?=&%#")


def _append_pdf_page_fragment(url: str | None, pdf_page_no: int | None) -> str | None:
    if not url or not pdf_page_no or "#page=" in url:
        return url
    return f"{url}#page={pdf_page_no}"


def _acquire_knowledge_operation_lock() -> None:
    if not _knowledge_operation_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Another knowledge-base operation is already in progress. Please wait for it to finish.",
        )


def _release_knowledge_operation_lock() -> None:
    if _knowledge_operation_lock.locked():
        _knowledge_operation_lock.release()


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
    filename: str
    title: str
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
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    parse_method = "binary_only"
    indexable = False
    if suffix == ".md":
        parse_method = "markdown"
        indexable = True
    elif suffix == ".txt":
        parse_method = "plain_text"
        indexable = True
    elif suffix in PDF_EXTENSIONS:
        parse_method = "ocr_pdf"
        indexable = True
    elif suffix in OFFICE_EXTENSIONS:
        parse_method = "markitdown_office"
        indexable = True

    urls = _build_global_urls(filename)
    return {
        "source_filename": filename,
        "display_title": Path(filename).stem,
        "source_extension": suffix,
        "source_size": size,
        "content_type": content_type,
        "parse_method": parse_method,
        "parse_status": "queued" if indexable else "uploaded",
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
        "error": None,
        "replace_existing_index": False,
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
            "parse_status": "parsed",
            "structured_filename": structured_filename,
            "structured_path": structured_path,
            "structured_artifact_url": None,
            "index_target_filename": structured_filename,
            "index_target_path": structured_path,
            "index_target_artifact_url": None,
            "index_target_format": "structured_json",
            "error": None,
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
        }
    )
    return record


def _mark_global_records_indexed() -> None:
    docs_dir = get_global_docs_dir()
    for record in _list_global_records():
        target_path = record.get("index_target_path")
        if not record.get("indexable") or not target_path:
            continue
        if not Path(str(target_path)).exists():
            continue
        record["parse_status"] = "indexed"
        _save_global_record(record["source_filename"], record)


def _process_global_knowledge_uploads(filenames: list[str]) -> None:
    """Parse uploaded global knowledge files and rebuild the index in the background."""
    try:
        docs_dir = get_global_docs_dir()
        ingestion_dir = get_global_ingestion_dir()
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
                if file_ext in PDF_EXTENSIONS:
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
                    record = _mark_global_record_parsed(
                        record,
                        structured_filename=structured_path.name,
                        structured_path=str(structured_path),
                    )
                    needs_reindex = True
                    parsed_filenames.append(safe_filename)
                elif file_ext in OFFICE_EXTENSIONS:
                    extracted_text = extract_office_text_with_markitdown(file_path)
                    if extracted_text and extracted_text.strip():
                        structured_payload = build_structured_document(
                            source_filename=safe_filename,
                            title=record["display_title"],
                            text=extracted_text,
                            parser_name=record["parse_method"],
                            hints=record.get("hints") or {},
                        )
                        structured_path = save_structured_document(
                            ingestion_dir,
                            safe_filename,
                            structured_payload,
                        )
                        record = _mark_global_record_parsed(
                            record,
                            structured_filename=structured_path.name,
                            structured_path=str(structured_path),
                        )
                        needs_reindex = True
                        parsed_filenames.append(safe_filename)
                    else:
                        record = _mark_global_record_failed(record, "Office parser returned no text")
                elif file_ext in INDEXABLE_EXTENSIONS:
                    structured_payload = build_structured_document(
                        source_filename=safe_filename,
                        title=record["display_title"],
                        text=file_path.read_text(encoding="utf-8"),
                        parser_name=record["parse_method"],
                        hints=record.get("hints") or {},
                    )
                    structured_path = save_structured_document(
                        ingestion_dir,
                        safe_filename,
                        structured_payload,
                    )
                    record = _mark_global_record_parsed(
                        record,
                        structured_filename=structured_path.name,
                        structured_path=str(structured_path),
                        preview_filename=safe_filename,
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
            rebuild_global_knowledge_index()
            _mark_global_records_indexed()
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
) -> KnowledgeUploadResponse:
    """Upload files into the global knowledge base and reindex them."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    _acquire_knowledge_operation_lock()
    lock_handed_to_background = False
    try:
        docs_dir = get_global_docs_dir()
        uploaded_files: list[dict[str, Any]] = []
        queued_filenames: list[str] = []
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

                record = _build_global_ingestion_record(
                    filename=safe_filename,
                    size=file_size,
                    content_type=file.content_type,
                    hints=hints,
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

                _save_global_record(safe_filename, record)
                uploaded_files.append(file_info)
                if record.get("indexable"):
                    queued_filenames.append(safe_filename)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to upload {safe_filename}: {exc}")

        if queued_filenames:
            background_tasks.add_task(_process_global_knowledge_uploads, queued_filenames)
            lock_handed_to_background = True

        return KnowledgeUploadResponse(
            success=True,
            files=uploaded_files,
            message=f"Successfully uploaded {len(uploaded_files)} file(s); parsing and indexing are running in the background",
        )
    finally:
        if not lock_handed_to_background:
            _release_knowledge_operation_lock()
    


@router.get("/uploads/list", response_model=dict, summary="List Global Knowledge Uploads")
def list_global_knowledge_files() -> dict:
    """List files currently stored in the global knowledge directory."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    docs_dir = get_global_docs_dir()
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
            "filename": file_path.name,
            "size": stat.st_size,
            "extension": file_path.suffix,
            "modified": stat.st_mtime,
            "artifact_url": _build_global_urls(file_path.name)["source_url"],
        }
        if record:
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
                }
            )
        else:
            entry.update(
                {
                    "parse_method": "static",
                    "parse_status": "indexed" if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else "uploaded",
                    "indexable": file_path.suffix.lower() in INDEXABLE_EXTENSIONS,
                    "preview_filename": file_path.name if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else None,
                    "preview_artifact_url": _build_global_urls(file_path.name)["source_url"] if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else None,
                    "structured_filename": None,
                    "structured_artifact_url": None,
                    "index_target_filename": file_path.name if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else None,
                    "index_target_artifact_url": _build_global_urls(file_path.name)["source_url"] if file_path.suffix.lower() in INDEXABLE_EXTENSIONS else None,
                    "hints": {},
                    "error": None,
                }
            )
        files.append(entry)

    return {"files": files, "count": len(files)}


@router.delete("/uploads/{filename}", response_model=dict, summary="Delete Global Knowledge Upload")
async def delete_global_knowledge_file(filename: str) -> dict:
    """Delete a file from the global knowledge directory and rebuild the global index."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

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

        rebuild_global_knowledge_index()
        _mark_global_records_indexed()
        return {
            "success": True,
            "message": f"Deleted {filename} from global knowledge base and rebuilt the index",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {exc}")
    finally:
        _release_knowledge_operation_lock()


@router.get("/search", response_model=SearchResponse, summary="Search Knowledge Base")
def search_knowledge_base(
    q: str = Query(..., description="Search query"),
    thread_id: str | None = Query(default=None, description="Optional thread ID to include uploaded docs"),
    doc_ids: str | None = Query(default=None, description="Optional comma-separated doc_ids to filter candidate books"),
) -> SearchResponse:
    """Search the knowledge base for relevant documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    try:
        retriever = get_retriever()
        parsed_doc_ids = [item.strip() for item in doc_ids.split(",") if item.strip()] if doc_ids else None
        results = retriever.search(q, thread_id=thread_id, doc_ids=parsed_doc_ids)
        
        search_results = [
            SearchResult(
                content=res["content"],
                score=res["score"],
                filename=res["filename"],
                source=res["source"],
                line_start=res.get("metadata", {}).get("line_start"),
                line_end=res.get("metadata", {}).get("line_end"),
                page_no=res.get("metadata", {}).get("page_no"),
                pdf_page_no=res.get("metadata", {}).get("pdf_page_no"),
                book_page_no=res.get("metadata", {}).get("book_page_no"),
                paragraph_no=res.get("metadata", {}).get("paragraph_no"),
                bbox=res.get("metadata", {}).get("bbox"),
                source_url=(
                    _encode_url_path(
                        (
                            f"/api/threads/{res.get('metadata', {}).get('thread_id')}/artifacts{res.get('metadata', {}).get('source_virtual_path')}?page={res.get('page')}"
                            if res.get("source_type") == "pdf" and res.get("page") is not None
                            else _append_pdf_page_fragment(
                                f"/api/threads/{res.get('metadata', {}).get('thread_id')}/artifacts{res.get('metadata', {}).get('source_virtual_path')}",
                                res.get("metadata", {}).get("pdf_page_no"),
                            )
                        )
                    )
                    if res.get("metadata", {}).get("scope") == "thread"
                    else _encode_url_path(
                        (
                            f"/api/knowledge/docs/{res['filename']}?page={res.get('page')}"
                            if res.get("source_type") == "pdf" and res.get("page") is not None
                            else _append_pdf_page_fragment(
                                f"/api/knowledge/docs/{res['filename']}",
                                res.get("metadata", {}).get("pdf_page_no"),
                            )
                        )
                    )
                ),
                original_url=(
                    _encode_url_path(
                        (
                            f"/api/threads/{res.get('metadata', {}).get('thread_id')}/artifacts{res.get('metadata', {}).get('origin_virtual_path')}?page={res.get('page')}"
                            if res.get("source_type") == "pdf" and res.get("page") is not None
                            else _append_pdf_page_fragment(
                                f"/api/threads/{res.get('metadata', {}).get('thread_id')}/artifacts{res.get('metadata', {}).get('origin_virtual_path')}",
                                res.get("metadata", {}).get("pdf_page_no"),
                            )
                        )
                    )
                    if res.get("metadata", {}).get("scope") == "thread" and res.get("metadata", {}).get("origin_virtual_path")
                    else (
                        _encode_url_path(
                            (
                                f"/api/knowledge/docs/{res.get('metadata', {}).get('origin_filename')}?page={res.get('page')}"
                                if res.get("source_type") == "pdf" and res.get("page") is not None
                                else _append_pdf_page_fragment(
                                    f"/api/knowledge/docs/{res.get('metadata', {}).get('origin_filename')}",
                                    res.get("metadata", {}).get("pdf_page_no"),
                                )
                            )
                        )
                        if res.get("metadata", {}).get("scope") == "global" and res.get("metadata", {}).get("origin_filename")
                        else None
                    )
                ),
                page=res.get("page"),
                source_type=res.get("source_type", "unknown"),
            )
            for res in results
        ]
        
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
        filename=document.filename,
        title=document.title,
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
