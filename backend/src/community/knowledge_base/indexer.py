"""
Script to index documents into the knowledge base.
"""

import os
from pathlib import Path
from typing import List

from langchain_community.document_loaders import DirectoryLoader
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Distance, VectorParams

from src.community.knowledge_base.retriever import get_embedding_model, get_qdrant_client
from src.config.knowledge_base_config import get_knowledge_base_config


def run_indexer():
    """Index documents from the knowledge base directory."""
    print("Starting knowledge base indexer...")
    
    # Reload config to ensure we have latest settings
    from src.config.app_config import get_app_config
    config = get_app_config()
    kb_config = config.knowledge_base

    if not kb_config.enabled:
        print("Knowledge base is disabled in config. To enable provided 'enabled: true' in knowledge_base section.") 
        return

    docs_path = Path(kb_config.docs_path)
    if not docs_path.is_absolute():
        # Resolve relative to project root (assuming standard layout)
        project_root = Path(os.getcwd()).parent if Path(os.getcwd()).name == "backend" else Path(os.getcwd())
        if not (project_root / "backend").exists(): # try to find project root if we are deep
             project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        
        docs_path = project_root / kb_config.docs_path
    
    print(f"Reading documents from: {docs_path}")
    
    if not docs_path.exists():
        print(f"Creating documents directory: {docs_path}")
        docs_path.mkdir(parents=True, exist_ok=True)
        # Create a sample document
        sample_doc = docs_path / "welcome.md"
        with open(sample_doc, "w") as f:
            f.write("# Welcome to DeerFlow Knowledge Base\n\nThis is a sample document. Add your markdown files here to be indexed.")
        print(f"Created sample document: {sample_doc}")

    # Load documents
    documents = []
    
    # Helper to load safely
    def load_safe(loader_cls, glob_pattern):
        try:
            loader = DirectoryLoader(str(docs_path), glob=glob_pattern, loader_cls=loader_cls)
            docs = loader.load()
            print(f"Loaded {len(docs)} files matching '{glob_pattern}'")
            return docs
        except Exception as e:
            print(f"Warning: Failed to load pattern '{glob_pattern}': {e}")
            return []

    documents.extend(load_safe(UnstructuredMarkdownLoader, "**/*.md"))
    documents.extend(load_safe(TextLoader, "**/*.txt"))
    
    if not documents:
        print("No documents found to index.")
        return

    print(f"Total documents found: {len(documents)}")

    # Split documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=kb_config.chunking.chunk_size,
        chunk_overlap=kb_config.chunking.chunk_overlap,
    )
    chunks = text_splitter.split_documents(documents)
    print(f"Created {len(chunks)} chunks.")

    # Get embeddings and client
    embeddings = get_embedding_model()
    client = get_qdrant_client()

    # Ensure Qdrant collection exists (create on first run)
    collection_name = kb_config.qdrant.collection_name
    try:
        client.get_collection(collection_name=collection_name)
        print(f"Using existing Qdrant collection: {collection_name}")
    except ValueError:
        print(f"Qdrant collection '{collection_name}' not found. Creating a new collection...")
        sample_embedding = embeddings.embed_query("deer-flow-knowledge-base-dimension-probe")
        vector_size = len(sample_embedding)
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
        print(f"Created Qdrant collection '{collection_name}' with vector size {vector_size}")

    # Initialize Vector Store
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    # Index chunks
    print("Indexing chunks to Qdrant...")
    vector_store.add_documents(chunks)
    
    print("Indexing complete!")


if __name__ == "__main__":
    run_indexer()
