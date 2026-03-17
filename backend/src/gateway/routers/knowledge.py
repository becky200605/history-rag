import logging
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.community.knowledge_base.retriever import get_retriever, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge-base"])


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
    page: int | None = None
    source_type: str = "unknown"


class SearchResponse(BaseModel):
    """Response model for search operation."""
    query: str
    results: list[SearchResult]


class UploadKnowledgeDocumentResponse(BaseModel):
    """Response model for uploading a knowledge base document."""

    status: str
    message: str
    filename: str
    markdown_filename: str | None = None


class KnowledgeDocumentInfo(BaseModel):
    """Metadata for a knowledge base document file."""

    filename: str
    size: int
    modified: float
    extension: str


class KnowledgeDocumentListResponse(BaseModel):
    """Response model for listing knowledge base documents."""

    docs: list[KnowledgeDocumentInfo]


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
def reindex_knowledge_base() -> ReindexResponse:
    """Trigger a full reindexing of the knowledge base documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    try:
        from src.community.knowledge_base.indexer import run_indexer

        run_indexer()
        return ReindexResponse(status="success", message="Knowledge base reindexed successfully")
    except Exception as e:
        logger.exception("Failed to reindex knowledge base")
        raise HTTPException(status_code=500, detail=f"Failed to reindex: {str(e)}")


@router.get("/search", response_model=SearchResponse, summary="Search Knowledge Base")
def search_knowledge_base(q: str = Query(..., description="Search query")) -> SearchResponse:
    """Search the knowledge base for relevant documents."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    try:
        retriever = get_retriever()
        results = retriever.search(q)
        
        search_results = [
            SearchResult(
                content=res["content"],
                score=res["score"],
                filename=res["filename"],
                source=res["source"],
                page=res.get("page"),
                source_type=res.get("source_type", "unknown"),
            )
            for res in results
        ]
        
        return SearchResponse(query=q, results=search_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


def _resolve_knowledge_docs_root() -> Path:
    """Resolve knowledge docs directory (same logic as indexer: relative to project root)."""
    docs_path = Path(get_knowledge_base_config().docs_path)
    if docs_path.is_absolute():
        return docs_path
    cwd = Path(os.getcwd())
    project_root = cwd.parent if cwd.name == "backend" else cwd
    if not (project_root / "backend").exists():
        # Fallback when running from other context
        project_root = cwd
    return project_root / get_knowledge_base_config().docs_path


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

    # Security: no path traversal
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = _resolve_knowledge_docs_root()
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
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    
    # Handle PDF files
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
    "/docs",
    response_model=KnowledgeDocumentListResponse,
    summary="List Knowledge Documents",
)
def list_knowledge_documents() -> KnowledgeDocumentListResponse:
    """List all files under the knowledge docs directory.

    This is primarily used by the frontend settings UI to manage documents.
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    docs_root = _resolve_knowledge_docs_root()
    if not docs_root.exists():
        return KnowledgeDocumentListResponse(docs=[])

    docs: list[KnowledgeDocumentInfo] = []
    for entry in sorted(docs_root.iterdir()):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        docs.append(
            KnowledgeDocumentInfo(
                filename=entry.name,
                size=stat.st_size,
                modified=stat.st_mtime,
                extension=entry.suffix,
            )
        )

    return KnowledgeDocumentListResponse(docs=docs)


@router.delete(
    "/docs/{filename}",
    summary="Delete Knowledge Document",
)
def delete_knowledge_document(filename: str) -> dict:
    """Delete a document from the knowledge docs directory."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    docs_root = _resolve_knowledge_docs_root()
    file_path = docs_root / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    # Security: ensure inside docs_root.
    try:
        file_path.resolve().relative_to(docs_root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        file_path.unlink()
        logger.info("Deleted knowledge document: %s", filename)
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:  # pragma: no cover - filesystem error path
        logger.exception("Failed to delete knowledge document %s", filename)
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.post(
    "/docs/upload",
    response_model=UploadKnowledgeDocumentResponse,
    summary="Upload Knowledge Document",
)
async def upload_knowledge_document(
    file: UploadFile = File(..., description="Knowledge document (.md, .markdown, .pdf, .txt)"),
    reindex: bool = Query(
        False,
        description="Whether to trigger a full reindex after upload (may be slow for large corpora).",
    ),
) -> UploadKnowledgeDocumentResponse:
    """Upload a knowledge base document.

    Supported formats: `.md`, `.markdown`, `.pdf`, `.txt`
    Files are saved directly under the knowledge docs directory and indexed natively.
    """
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    safe_filename = Path(file.filename).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = Path(safe_filename).suffix.lower()
    if ext not in {".md", ".markdown", ".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="Only .md, .markdown, .pdf and .txt files are supported for knowledge base uploads")

    docs_root = _resolve_knowledge_docs_root()
    docs_root.mkdir(parents=True, exist_ok=True)

    file_path = docs_root / safe_filename

    try:
        content = await file.read()
        file_path.write_bytes(content)
    except Exception as e:
        logger.exception("Failed to save uploaded knowledge document %s", safe_filename)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # For backward compatibility, markdown_filename is set to the original filename
    markdown_filename: str | None = file_path.name if ext in {".md", ".markdown"} else None

    if reindex:
        try:
            from src.community.knowledge_base.indexer import run_indexer

            run_indexer()
        except Exception as e:
            logger.exception("File uploaded but failed to reindex knowledge base")
            raise HTTPException(
                status_code=500,
                detail=f"File uploaded (markdown: {markdown_filename}) but reindex failed: {e}",
            )

    return UploadKnowledgeDocumentResponse(
        status="success",
        message="Knowledge document uploaded successfully",
        filename=safe_filename,
        markdown_filename=markdown_filename,
    )
