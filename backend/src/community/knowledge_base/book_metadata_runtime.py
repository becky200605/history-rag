"""Runtime helpers for AI-generated book metadata."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from langchain_core.messages import HumanMessage, SystemMessage

from src.community.knowledge_base.book_metadata import (
    BookMetadataRecord,
    build_book_metadata_prompt_bundle,
    build_book_metadata_record,
    parse_book_metadata_suggestion,
    save_book_metadata,
)
from src.config.knowledge_base_config import BookMetadataConfig

logger = logging.getLogger(__name__)


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
    )

    model = create_chat_model(name=config.model_name, thinking_enabled=False)
    response = model.invoke(
        [
            SystemMessage(content=prompt_bundle.system_prompt),
            HumanMessage(content=prompt_bundle.user_prompt),
        ]
    )
    response_text = _strip_markdown_fences(str(response.content or ""))
    if not response_text:
        raise ValueError("Book metadata model returned empty content")

    suggestion = parse_book_metadata_suggestion(response_text)
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
