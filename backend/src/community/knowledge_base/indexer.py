"""Index documents into the knowledge base."""

import json
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import Distance, VectorParams

from src.community.knowledge_base.common import derive_global_doc_id
from src.community.knowledge_base.common import derive_thread_doc_id
from src.community.knowledge_base.common import extract_title_from_text
from src.community.knowledge_base.common import get_thread_collection_name
from src.community.knowledge_base.common import resolve_project_path
from src.community.knowledge_base.ingestion import build_record_lookup, list_ingestion_records
from src.community.knowledge_base.retriever import get_embedding_model, get_qdrant_client
from src.community.knowledge_base.structured_document import build_bbox_from_position, load_structured_document
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

INDEXABLE_EXTENSIONS = {".md", ".txt", ".pdf"}
STRUCTURED_INDEXABLE_EXTENSIONS = INDEXABLE_EXTENSIONS | {".json"}


def _load_safe_directory(loader_cls, docs_path: Path, glob_pattern: str) -> list[Document]:
    try:
        loader = DirectoryLoader(str(docs_path), glob=glob_pattern, loader_cls=loader_cls)
        return loader.load()
    except Exception as exc:
        print(f"Warning: failed to load '{glob_pattern}': {exc}")
        return []


def _load_pdf_documents(path: Path) -> list[Document]:
    try:
        loader = PyMuPDFLoader(str(path))
        documents = loader.load()
    except Exception as exc:
        print(f"Warning: failed to load PDF '{path}': {exc}")
        return []

    for document in documents:
        document.metadata["filename"] = path.name
        document.metadata["source_type"] = "pdf"
        document.metadata["page"] = document.metadata.get("page", 0)
        document.metadata.setdefault("source", str(path))
    return documents


def _load_structured_documents(path: Path) -> list[Document]:
    payload = load_structured_document(path)
    if not payload:
        return []

    documents: list[Document] = []
    for page in payload.get("pages", []):
        page_no = page.get("page_no")
        pdf_page_no = page.get("pdf_page_no") or page_no
        book_page_no = page.get("book_page_no")
        page_number_source = page.get("page_number_source")
        for paragraph in page.get("paragraphs", []):
            paragraph_text = str(paragraph.get("text", "")).strip()
            if not paragraph_text:
                continue
            documents.append(
                Document(
                    page_content=paragraph_text,
                    metadata={
                        "source": str(path),
                        "page_no": page_no,
                        "pdf_page_no": pdf_page_no,
                        "book_page_no": book_page_no,
                        "page_number_source": page_number_source,
                        "page_meta": page.get("meta"),
                        "paragraph_id": paragraph.get("paragraph_id"),
                        "paragraph_no": paragraph.get("paragraph_no"),
                        "paragraph_no_in_doc": paragraph.get("paragraph_no_in_doc"),
                        "line_start": paragraph.get("line_start"),
                        "line_end": paragraph.get("line_end"),
                        "bbox": paragraph.get("bbox")
                        or build_bbox_from_position(paragraph.get("position")),
                        "bbox_source": paragraph.get("bbox_source"),
                        "structured_source_filename": payload.get("source_filename"),
                        "structured_title": payload.get("title"),
                        "parser_name": payload.get("parser_name"),
                        "source_type": "structured",
                    },
                )
            )
    return documents


def _load_documents_from_paths(paths: list[Path]) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(paths):
        try:
            suffix = path.suffix.lower()
            if suffix == ".json":
                documents.extend(_load_structured_documents(path))
            elif suffix == ".md":
                loaded = UnstructuredMarkdownLoader(str(path)).load()
                for document in loaded:
                    document.metadata["source_type"] = "markdown"
                documents.extend(loaded)
            elif suffix == ".txt":
                loaded = TextLoader(str(path), encoding="utf-8").load()
                for document in loaded:
                    document.metadata["source_type"] = "text"
                documents.extend(loaded)
            elif suffix == ".pdf":
                documents.extend(_load_pdf_documents(path))
        except Exception as exc:
            print(f"Warning: failed to load '{path}': {exc}")
    return documents


def _ensure_collection(client, collection_name: str, embeddings) -> None:
    try:
        client.get_collection(collection_name=collection_name)
        return
    except Exception:
        pass

    sample_embedding = embeddings.embed_query("history-rag-collection-probe")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=len(sample_embedding), distance=Distance.COSINE),
    )


def _replace_collection(client, collection_name: str, embeddings) -> None:
    try:
        client.delete_collection(collection_name=collection_name)
    except Exception:
        pass
    _ensure_collection(client, collection_name, embeddings)


def _clear_collection_if_exists(client, collection_name: str) -> None:
    try:
        client.delete_collection(collection_name=collection_name)
    except Exception:
        pass


def _annotate_chunks(
    chunks: list[Document],
    source_text_by_path: dict[str, str],
    scope: str,
    thread_id: str | None,
) -> list[Document]:
    chunk_counts: dict[str, int] = {}

    for chunk in chunks:
        source = str(chunk.metadata.get("source", ""))
        source_text = source_text_by_path.get(source, "")
        start_index = int(chunk.metadata.get("start_index", 0) or 0)
        existing_line_start = chunk.metadata.get("line_start")
        existing_line_end = chunk.metadata.get("line_end")
        line_start = (
            existing_line_start
            if existing_line_start is not None
            else (source_text[:start_index].count("\n") + 1 if source_text else None)
        )
        line_end = (
            existing_line_end
            if existing_line_end is not None
            else (line_start + chunk.page_content.count("\n") if line_start is not None else None)
        )

        chunk_index = chunk_counts.get(source, 0)
        chunk_counts[source] = chunk_index + 1

        chunk.metadata.update(
            {
                "filename": chunk.metadata.get("filename") or (Path(source).name if source else "Unknown"),
                "source_path": source,
                "scope": scope,
                "thread_id": thread_id,
                "chunk_index": chunk_index,
                "line_start": line_start,
                "line_end": line_end,
                "page": chunk.metadata.get("page"),
                "page_no": chunk.metadata.get("page_no"),
                "pdf_page_no": chunk.metadata.get("pdf_page_no"),
                "book_page_no": chunk.metadata.get("book_page_no"),
                "page_number_source": chunk.metadata.get("page_number_source"),
                "page_meta": chunk.metadata.get("page_meta"),
                "paragraph_id": chunk.metadata.get("paragraph_id"),
                "paragraph_no": chunk.metadata.get("paragraph_no"),
                "paragraph_no_in_doc": chunk.metadata.get("paragraph_no_in_doc"),
                "bbox": chunk.metadata.get("bbox"),
                "bbox_source": chunk.metadata.get("bbox_source"),
                "source_type": chunk.metadata.get("source_type", "unknown"),
            }
        )

    return chunks


def _build_chunks(documents: list[Document], scope: str, thread_id: str | None) -> list[Document]:
    kb_config = get_knowledge_base_config()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=kb_config.chunking.chunk_size,
        chunk_overlap=kb_config.chunking.chunk_overlap,
        add_start_index=True,
    )
    source_text_by_path = {
        str(document.metadata.get("source", "")): document.page_content
        for document in documents
        if document.metadata.get("source")
    }
    chunks = splitter.split_documents(documents)
    return _annotate_chunks(chunks, source_text_by_path, scope=scope, thread_id=thread_id)


def index_documents(
    documents: list[Document],
    collection_name: str,
    scope: str,
    thread_id: str | None = None,
) -> int:
    """Replace a collection with freshly indexed documents."""
    if not documents:
        return 0

    chunks = _build_chunks(documents, scope=scope, thread_id=thread_id)
    embeddings = get_embedding_model()
    client = get_qdrant_client()

    _replace_collection(client, collection_name, embeddings)

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )
    vector_store.add_documents(chunks)
    return len(chunks)


def rebuild_global_knowledge_index() -> int:
    """Rebuild the shared knowledge-base collection from repo docs."""
    kb_config = get_knowledge_base_config()
    docs_path = resolve_project_path(kb_config.docs_path)
    ingestion_dir = docs_path / ".ingestion"

    if not docs_path.exists():
        docs_path.mkdir(parents=True, exist_ok=True)
        sample_doc = docs_path / "welcome.md"
        sample_doc.write_text(
            "# Welcome to DeerFlow Knowledge Base\n\nThis is a sample document. Add your markdown files here to be indexed.",
            encoding="utf-8",
        )

    documents: list[Document] = []
    structured_paths: list[Path] = []
    preview_filenames_to_skip: set[str] = set()
    records_by_source_filename: dict[str, dict[str, object]] = {}

    if ingestion_dir.exists():
        for path in sorted(ingestion_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("schema_version") == 1 and str(path.name).endswith(".structured.json"):
                structured_paths.append(path)
                continue
            source_filename = payload.get("source_filename")
            if source_filename:
                records_by_source_filename[str(source_filename)] = payload
            preview_filename = payload.get("preview_filename")
            if preview_filename:
                preview_filenames_to_skip.add(str(preview_filename))

    if structured_paths:
        documents.extend(_load_documents_from_paths(structured_paths))

    documents.extend(
        document
        for document in _load_safe_directory(UnstructuredMarkdownLoader, docs_path, "**/*.md")
        if Path(str(document.metadata.get("source", ""))).name not in preview_filenames_to_skip
        and "/.ingestion/" not in str(document.metadata.get("source", ""))
    )
    documents.extend(
        document
        for document in _load_safe_directory(TextLoader, docs_path, "**/*.txt")
        if Path(str(document.metadata.get("source", ""))).name not in preview_filenames_to_skip
        and "/.ingestion/" not in str(document.metadata.get("source", ""))
    )

    raw_pdf_paths = [
        path
        for path in sorted(docs_path.glob("**/*.pdf"))
        if "/.ingestion/" not in str(path)
        and path.name not in records_by_source_filename
    ]
    if raw_pdf_paths:
        documents.extend(_load_documents_from_paths(raw_pdf_paths))

    if not documents:
        return 0

    for document in documents:
        source_path = Path(str(document.metadata.get("source", "")))
        if not source_path.name:
            continue
        source_filename = document.metadata.get("structured_source_filename") or source_path.name
        global_record = records_by_source_filename.get(str(source_filename), {})
        title = document.metadata.get("structured_title") or Path(str(source_filename)).stem
        document.metadata["doc_id"] = derive_global_doc_id(docs_path, Path(str(source_filename)))
        document.metadata["title"] = title
        document.metadata["filename"] = str(global_record.get("preview_filename") or source_filename)
        document.metadata["detected_title"] = extract_title_from_text(
            document.page_content[:800],
            source_path.stem,
        )
        if global_record.get("preview_filename"):
            document.metadata["preview_filename"] = global_record.get("preview_filename")
        if (
            global_record.get("source_filename")
            and global_record.get("source_filename") != global_record.get("preview_filename")
        ):
            document.metadata["origin_filename"] = global_record.get("source_filename")

    return index_documents(
        documents,
        collection_name=kb_config.qdrant.collection_name,
        scope="global",
        thread_id=None,
    )


def rebuild_thread_upload_index(thread_id: str) -> int:
    """Rebuild the per-thread upload collection from indexed upload files."""
    kb_config = get_knowledge_base_config()
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    collection_name = get_thread_collection_name(kb_config.qdrant.collection_name, thread_id)

    if not uploads_dir.exists():
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    _, records_by_index_target = build_record_lookup(thread_id)
    candidate_paths: list[Path] = []
    seen_paths: set[Path] = set()
    preview_filenames_to_skip: set[str] = set()
    recorded_source_filenames: set[str] = set()

    for record in list_ingestion_records(thread_id):
        target_filename = record.get("index_target_filename")
        target_path = record.get("index_target_path")
        preview_filename = record.get("preview_filename")
        source_filename = record.get("source_filename")
        if preview_filename:
            preview_filenames_to_skip.add(str(preview_filename))
            recorded_source_filenames.add(str(preview_filename))
        if source_filename:
            recorded_source_filenames.add(str(source_filename))
        if target_filename:
            recorded_source_filenames.add(str(target_filename))
        if not record.get("indexable") or not target_filename or not target_path:
            continue
        path = Path(str(target_path))
        if not path.exists() or path in seen_paths:
            continue
        candidate_paths.append(path)
        seen_paths.add(path)

    for path in uploads_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTENSIONS:
            continue
        if path.name in preview_filenames_to_skip or path.name in recorded_source_filenames:
            continue
        if path in seen_paths:
            continue
        candidate_paths.append(path)
        seen_paths.add(path)

    if not candidate_paths:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    documents = _load_documents_from_paths(candidate_paths)
    if not documents:
        _clear_collection_if_exists(get_qdrant_client(), collection_name)
        return 0

    for document in documents:
        source_path = Path(str(document.metadata.get("source", "")))
        if not source_path.name:
            continue
        ingestion_record = records_by_index_target.get(source_path.name)

        document.metadata["scope"] = "thread"
        document.metadata["thread_id"] = thread_id
        document.metadata["filename"] = source_path.name
        if ingestion_record:
            source_filename = ingestion_record.get("source_filename", source_path.name)
            document.metadata["doc_id"] = derive_thread_doc_id(Path(source_filename))
            document.metadata["title"] = ingestion_record.get("display_title", Path(source_filename).stem)
            preview_filename = ingestion_record.get("preview_filename") or source_filename
            document.metadata["filename"] = preview_filename
            document.metadata["parse_method"] = ingestion_record.get("parse_method")
            document.metadata["parse_status"] = ingestion_record.get("parse_status")
            hints = ingestion_record.get("hints") or {}
            for key, value in hints.items():
                document.metadata[key] = value
            source_virtual_path = (
                ingestion_record.get("preview_virtual_path")
                or ingestion_record.get("source_virtual_path")
            )
            if source_virtual_path:
                document.metadata["source_virtual_path"] = source_virtual_path
            if source_filename != preview_filename:
                document.metadata["origin_filename"] = source_filename
                document.metadata["origin_virtual_path"] = ingestion_record.get("source_virtual_path")
        else:
            document.metadata["doc_id"] = derive_thread_doc_id(source_path)
            document.metadata["title"] = source_path.stem
        document.metadata["detected_title"] = extract_title_from_text(
            document.page_content[:800],
            source_path.stem,
        )

        if "origin_virtual_path" not in document.metadata and source_path.suffix.lower() == ".md":
            for sibling in uploads_dir.glob(f"{source_path.stem}.*"):
                if sibling == source_path:
                    continue
                if sibling.suffix.lower() in INDEXABLE_EXTENSIONS:
                    continue
                document.metadata["origin_filename"] = sibling.name
                document.metadata["origin_virtual_path"] = f"/mnt/user-data/uploads/{sibling.name}"
                break

        if "source_virtual_path" not in document.metadata:
            document.metadata["source_virtual_path"] = f"/mnt/user-data/uploads/{source_path.name}"

    return index_documents(
        documents,
        collection_name=collection_name,
        scope="thread",
        thread_id=thread_id,
    )


def run_indexer() -> None:
    """CLI entrypoint for rebuilding the shared knowledge-base index."""
    print("Starting knowledge base indexer...")
    from src.config.app_config import get_app_config

    config = get_app_config()
    kb_config = config.knowledge_base
    if not kb_config.enabled:
        print("Knowledge base is disabled in config. Set knowledge_base.enabled=true to enable indexing.")
        return

    indexed_chunks = rebuild_global_knowledge_index()
    print(f"Indexing complete. Indexed {indexed_chunks} chunks into '{kb_config.qdrant.collection_name}'.")


if __name__ == "__main__":
    run_indexer()
