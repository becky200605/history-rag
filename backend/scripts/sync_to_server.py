#!/usr/bin/env python3
"""
Watch res/ and sync completed OCR results to the server.

For each new parsed file:
  1. Generate AI metadata (summary, categories, eras, regions, ...)
  2. *.pdf.json + *.pdf.structured.json  →  server:.ingestion/
  3. .book-metadata/*.book-metadata.json →  server:docs/.book-metadata/
  4. done/*.pdf                          →  server:docs/

Usage:
    python scripts/sync_to_server.py --res ./res --config ../config.yaml --watch

    # custom host / paths
    python scripts/sync_to_server.py --res ./res --config ../config.yaml \\
        --host root@124.221.234.124 \\
        --remote-docs /var/lib/history-rag/knowledge/docs \\
        --watch

Ctrl-C to stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import logging
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MARKER_SUFFIX = ".synced"


# ---------------------------------------------------------------------------
# App config
# ---------------------------------------------------------------------------

def _setup_app_config(config_path: str) -> None:
    from src.config.app_config import reload_app_config
    from src.config.knowledge_base_config import load_knowledge_base_config_from_dict

    app_config = reload_app_config(config_path)
    # Use the already env-var-resolved KB config from AppConfig
    load_knowledge_base_config_from_dict(app_config.knowledge_base.model_dump())


# ---------------------------------------------------------------------------
# Metadata generation
# ---------------------------------------------------------------------------

def _generate_metadata(filename: str, res_dir: Path, model_name: str | None) -> str | None:
    """Generate AI metadata from the structured JSON and save to res/.book-metadata/.
    Returns the suggested folder_path on success, None on failure."""
    from src.community.knowledge_base.book_metadata import get_book_metadata_dir
    from src.community.knowledge_base.book_metadata_runtime import generate_book_metadata_record
    from src.config.knowledge_base_config import BookMetadataConfig

    structured_path = res_dir / f"{filename}.structured.json"
    if not structured_path.exists():
        logger.warning("META  %s  structured JSON missing, skipping metadata", filename)
        return None

    try:
        structured_payload = json.loads(structured_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("META  %s  cannot read structured JSON: %s", filename, exc)
        return None

    record_path = res_dir / f"{filename}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    title = str(record.get("display_title") or Path(filename).stem)

    metadata_dir = get_book_metadata_dir(res_dir)
    metadata_dir.mkdir(exist_ok=True)

    config = BookMetadataConfig(enabled=True, model_name=model_name)
    logger.info("META  %s  generating (summary / categories / eras ...)", filename)
    try:
        meta_record, saved_path = generate_book_metadata_record(
            structured_payload=structured_payload,
            source_filename=filename,
            title=title,
            output_dir=res_dir,
            config=config,
        )
        suggestion = meta_record.suggestion
        folder: str | None = None
        if suggestion:
            folder = getattr(getattr(suggestion, "folder", None), "value", None)
            summary_field = getattr(suggestion, "summary", None)
            summary = str(getattr(summary_field, "value", "") or "")[:80]
            logger.info("META  %s  folder=%s  summary=%s...", filename, folder, summary)
        return folder
    except Exception as exc:
        logger.warning("META  %s  failed (non-fatal): %s", filename, exc)
        return None


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _count_folders(registry_path: Path) -> int:
    try:
        return len(json.loads(registry_path.read_text(encoding="utf-8")).get("folders") or [])
    except Exception:
        return 0


def _marker(res_dir: Path, filename: str) -> Path:
    return res_dir / f"{filename}{MARKER_SUFFIX}"


def _is_synced(res_dir: Path, filename: str) -> bool:
    return _marker(res_dir, filename).exists()


def _mark_synced(res_dir: Path, filename: str) -> None:
    _marker(res_dir, filename).touch()


def _ensure_remote_dirs(host: str, remote_docs: str) -> None:
    """Create required remote directories via SSH (one round-trip)."""
    dirs = f"{remote_docs} {remote_docs}/.ingestion {remote_docs}/.book-metadata"
    subprocess.run(["ssh", host, f"mkdir -p {dirs}"], check=True)


def _rsync(local: Path, remote: str) -> None:
    subprocess.run(["rsync", "-az", str(local), remote], check=True)


def _scan(res_dir: Path, force: bool = False) -> list[str]:
    results = []
    for p in sorted(res_dir.glob("*.pdf.json")):
        filename = p.stem  # "book.pdf"
        if not force and _is_synced(res_dir, filename):
            continue
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if record.get("parse_status") != "parsed":
            continue
        if not (res_dir / f"{filename}.structured.json").exists():
            continue
        results.append(filename)
    return results


def _sync_one(filename: str, res_dir: Path, host: str, remote_docs: str, model_name: str | None, skip_metadata: bool) -> None:
    ingestion_dst = f"{host}:{remote_docs}/.ingestion/"
    metadata_dst = f"{host}:{remote_docs}/.book-metadata/"
    pdf_dst = f"{host}:{remote_docs}/"

    # Step 1: AI metadata (before sync, so we can upload it too)
    if not skip_metadata:
        folder_path = _generate_metadata(filename, res_dir, model_name)
        # Write folder_path back into the ingestion record so the server sees it
        if folder_path:
            record_path = res_dir / f"{filename}.json"
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if not record.get("folder_path"):
                    record["folder_path"] = folder_path
                    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.info("META  %s  folder_path written to record", filename)
            except Exception as exc:
                logger.warning("META  %s  could not update folder_path in record: %s", filename, exc)

    # Step 2: ingestion record + structured JSON → .ingestion/
    logger.info("SYNC  %s  → .ingestion/", filename)
    _rsync(res_dir / f"{filename}.json", ingestion_dst)
    _rsync(res_dir / f"{filename}.structured.json", ingestion_dst)

    # Step 3: book metadata sidecar → .book-metadata/
    metadata_file = res_dir / ".book-metadata" / f"{filename}.book-metadata.json"
    if metadata_file.exists():
        logger.info("SYNC  %s  → .book-metadata/", filename)
        _rsync(metadata_file, metadata_dst)

    # Step 4: source PDF → docs/
    pdf_file = res_dir / "done" / filename
    if pdf_file.exists():
        logger.info("SYNC  %s  → docs/", filename)
        _rsync(pdf_file, pdf_dst)
    else:
        logger.warning("SYNC  %s  PDF not in done/ — skipping PDF upload", filename)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _run(args: argparse.Namespace) -> int:
    res_dir = Path(args.res).resolve()
    if not res_dir.is_dir():
        logger.error("res dir not found: %s", res_dir)
        return 1

    if not args.skip_metadata:
        if not args.config:
            logger.error("--config is required for metadata generation (or pass --skip-metadata)")
            return 1
        try:
            _setup_app_config(args.config)
        except Exception as exc:
            logger.error("Failed to load config: %s", exc)
            return 1

    def _stop(*_):
        logger.info("Interrupted.")
        os._exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Ensure remote dirs exist (one SSH round-trip)
    try:
        _ensure_remote_dirs(args.host, args.remote_docs)
    except subprocess.CalledProcessError as exc:
        logger.error("Cannot create remote dirs (rc=%d) — check SSH access", exc.returncode)
        return 1

    # Download server's .folders.json so AI metadata sees the full folder tree
    remote_registry = f"{args.host}:{args.remote_docs}/.folders.json"
    local_registry = res_dir / ".folders.json"
    try:
        subprocess.run(["rsync", "-az", remote_registry, str(local_registry)], check=True)
        logger.info("Synced .folders.json from server (%d folders)", _count_folders(local_registry))
    except subprocess.CalledProcessError:
        logger.warning("No .folders.json on server yet — run fetch_remote_folders.py --write-registry first")

    logger.info("Watching %s  →  %s:%s  concurrency=%d  (poll every %ds)",
                res_dir, args.host, args.remote_docs, args.concurrency, args.poll_interval)

    with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix="sync") as pool:
        while True:
            pending = _scan(res_dir)
            if pending:
                futures = {
                    pool.submit(
                        _sync_one, f, res_dir, args.host, args.remote_docs,
                        args.metadata_model, args.skip_metadata
                    ): f
                    for f in pending
                }
                for fut in as_completed(futures):
                    filename = futures[fut]
                    try:
                        fut.result()
                        _mark_synced(res_dir, filename)
                        logger.info("DONE  %s", filename)
                    except subprocess.CalledProcessError as exc:
                        logger.error("FAIL  %s: rsync error (rc=%d)", filename, exc.returncode)
                    except Exception as exc:
                        logger.exception("FAIL  %s: %s", filename, exc)

            if not args.watch:
                break
            time.sleep(args.poll_interval)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync completed OCR results to the server.")
    parser.add_argument("--res", default="./res", metavar="DIR",
                        help="Local res/ directory (default: ./res)")
    parser.add_argument("--host", default="root@124.221.234.124", metavar="USER@HOST")
    parser.add_argument("--remote-docs", default="/var/lib/history-rag/knowledge/docs", metavar="PATH")
    parser.add_argument("--watch", action="store_true",
                        help="Keep running and pick up new files as they appear")
    parser.add_argument("--poll-interval", type=int, default=15, metavar="SEC")
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="config.yaml — needed for AI metadata generation")
    parser.add_argument("--metadata-model", default=None, metavar="MODEL",
                        help="LLM model for metadata (default: app default)")
    parser.add_argument("--skip-metadata", action="store_true",
                        help="Skip AI metadata generation, sync files only")
    parser.add_argument("--concurrency", type=int, default=5, metavar="N",
                        help="Max parallel sync jobs (default: 5)")
    args = parser.parse_args()
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
