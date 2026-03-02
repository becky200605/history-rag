import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.community.knowledge_base.retriever import get_retriever, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config

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


class SearchResponse(BaseModel):
    """Response model for search operation."""
    query: str
    results: list[SearchResult]


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
        from src.community.knowledge_base.indexer import KnowledgeBaseIndexer
        indexer = KnowledgeBaseIndexer()
        indexer.index_documents()
        return ReindexResponse(status="success", message="Knowledge base reindexed successfully")
    except Exception as e:
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
                source=res["source"]
            )
            for res in results
        ]
        
        return SearchResponse(query=q, results=search_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/docs/{filename}", summary="Get Knowledge Document")
def get_knowledge_document(filename: str, download: bool = False):
    """Get a knowledge document by filename."""
    config = get_knowledge_base_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Knowledge base is not enabled")
    
    # Resolve paths
    # Handle docs_path relative to project root or absolute
    docs_path = Path(config.docs_path)
    if not docs_path.is_absolute():
        # Logic to find project root (similar to indexer)
        # Assuming we are running from backend dir or similar context, 
        # but safely we should use a utility or config path resolver.
        # Here we rely on path traversal prevention by checking if file is within docs_path
        
        # Try to resolve relative to CWD first (backend dir usually)
        # But config docs_path is likely relative to project root (parent of backend)
        
        # Let's try to locate the file.
        # 1. relative to CWD
        candidate1 = Path(os.getcwd()) / config.docs_path / filename
        # 2. relative to project root (parent of CWD if CWD is backend)
        candidate2 = Path(os.getcwd()).parent / config.docs_path / filename
        
        if candidate1.exists():
            file_path = candidate1
        elif candidate2.exists():
            file_path = candidate2
        else:
             raise HTTPException(status_code=404, detail="Document not found")
    else:
        file_path = docs_path / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    # Security check: ensure file is within docs directory
    # simple check: ensure name doesn't contain path separators
    if "/" in filename or "\\" in filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    if download:
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    else:
        # Return as text/markdown for inline viewing
        return FileResponse(
            path=file_path,
            media_type="text/markdown"
        )
