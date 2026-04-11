"""Runtime helpers for AI-generated book metadata."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import sleep
from typing import Any, Mapping

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from src.community.knowledge_base.book_metadata import (
    BookMetadataRecord,
    build_book_metadata_prompt_bundle,
    build_book_metadata_record,
    get_book_metadata_dir,
    load_book_metadata,
    parse_book_metadata_suggestion,
    resolve_book_folder,
    save_book_metadata,
)
from src.config.knowledge_base_config import BookMetadataConfig

logger = logging.getLogger(__name__)
BOOK_METADATA_RETRY_ATTEMPTS = 3
BOOK_METADATA_RETRY_DELAY_SECONDS = 1.0


def _strip_markdown_fences(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("```"):
        return normalized

    lines = normalized.splitlines()
    if len(lines) <= 2:
        return normalized.strip("`")
    if lines[-1].strip() == "```":
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _is_retryable_metadata_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.HTTPError, json.JSONDecodeError)):
        return True
    if isinstance(exc, ValueError) and "empty content" in str(exc).lower():
        return True
    return exc.__class__.__name__ in {"APIConnectionError", "APITimeoutError", "RateLimitError"}


def build_existing_folder_tree(
    output_dir: Path,
    *,
    exclude_source_filename: str | None = None,
) -> str | None:
    """Render the current logical folder layout as a simple file tree."""
    metadata_dir = get_book_metadata_dir(output_dir)
    if not metadata_dir.exists():
        return None

    tree: dict[str, Any] = {}

    def _node_children(node: dict[str, Any]) -> dict[str, Any]:
        return node.setdefault("children", {})

    def _node_files(node: dict[str, Any]) -> list[str]:
        return node.setdefault("files", [])

    for path in sorted(metadata_dir.glob("*.book-metadata.json")):
        record = load_book_metadata(path)
        if record is None or record.source_filename == exclude_source_filename:
            continue
        folder = resolve_book_folder(record.suggestion)
        if not folder:
            continue
        node = tree
        for segment in folder.split("/"):
            node = _node_children(node).setdefault(segment, {})
        _node_files(node).append(record.source_filename)

    if not tree:
        return None

    lines = ["."]

    def _render(node: dict[str, Any], prefix: str = "") -> None:
        folders = sorted(_node_children(node).items(), key=lambda item: item[0])
        files = sorted(_node_files(node))
        entries: list[tuple[str, str, Any]] = [("folder", name, child) for name, child in folders]
        entries.extend(("file", name, None) for name in files)

        for index, (entry_type, name, child) in enumerate(entries):
            is_last = index == len(entries) - 1
            branch = "`-- " if is_last else "|-- "
            lines.append(f"{prefix}{branch}{name}{'/' if entry_type == 'folder' else ''}")
            if entry_type == "folder":
                _render(child, prefix + ("    " if is_last else "|   "))

    _render(tree)
    return "\n".join(lines)


def generate_book_metadata_record(
    *,
    structured_payload: Mapping[str, Any],
    source_filename: str,
    title: str,
    output_dir: Path,
    config: BookMetadataConfig,
) -> tuple[BookMetadataRecord, Path]:
    """Run an AI metadata pass and persist the resulting record."""
    from src.models import create_chat_model

    prompt_bundle = build_book_metadata_prompt_bundle(
        structured_payload,
        source_filename=source_filename,
        title=title,
        front_page_limit=config.front_page_limit,
        body_sample_count=config.body_sample_count,
        max_excerpt_chars=config.max_excerpt_chars,
        existing_folder_tree=build_existing_folder_tree(
            output_dir,
            exclude_source_filename=source_filename,
        ),
    )

    model = create_chat_model(name=config.model_name, thinking_enabled=False)
    messages = [
        SystemMessage(content=prompt_bundle.system_prompt),
        HumanMessage(content=prompt_bundle.user_prompt),
    ]
    suggestion = None
    last_error: Exception | None = None
    for attempt in range(1, BOOK_METADATA_RETRY_ATTEMPTS + 1):
        try:
            response = model.invoke(messages)
            response_text = _strip_markdown_fences(str(response.content or ""))
            if not response_text:
                raise ValueError("Book metadata model returned empty content")
            suggestion = parse_book_metadata_suggestion(response_text)
            break
        except Exception as exc:
            last_error = exc
            if not _is_retryable_metadata_error(exc) or attempt >= BOOK_METADATA_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "Book metadata generation transient failure for %s on attempt %s/%s: %s",
                source_filename,
                attempt,
                BOOK_METADATA_RETRY_ATTEMPTS,
                exc,
            )
            sleep(BOOK_METADATA_RETRY_DELAY_SECONDS)

    if suggestion is None:
        raise ValueError(f"Book metadata generation failed for {source_filename}: {last_error}")

    record = build_book_metadata_record(
        source_filename=source_filename,
        source_title=title,
        page_count=prompt_bundle.prompt_input.page_count,
        prompt_input=prompt_bundle.prompt_input,
        suggestion=suggestion,
        model_name=config.model_name,
    )
    return record, save_book_metadata(output_dir, source_filename, record)


def maybe_generate_book_metadata(
    *,
    structured_payload: Mapping[str, Any],
    source_filename: str,
    title: str,
    output_dir: Path,
    config: BookMetadataConfig | None,
) -> Path | None:
    """Best-effort metadata generation that never raises to callers."""
    if config is None or not config.enabled:
        return None

    try:
        _, output_path = generate_book_metadata_record(
            structured_payload=structured_payload,
            source_filename=source_filename,
            title=title,
            output_dir=output_dir,
            config=config,
        )
        return output_path
    except json.JSONDecodeError as exc:
        logger.warning("Book metadata generation returned invalid JSON for %s: %s", source_filename, exc)
    except Exception as exc:
        logger.warning("Book metadata generation failed for %s: %s", source_filename, exc)
    return None
