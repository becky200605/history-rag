"""Tests for general-purpose subagent system prompt multi-book retrieval guidelines."""
from src.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG


def test_subagent_prompt_encourages_specialized_sources() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Should prioritize specialized monographs over 通史
    assert "specialized" in prompt
    assert "specialized monographs" in prompt.lower() or "specialized" in prompt


def test_subagent_prompt_allows_second_book_search() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # A second focused book_search is explicitly allowed
    assert "second" in prompt.lower()
    assert "second focused" in prompt.lower() or "second `book_search`" in prompt or "second focused `book_search`" in prompt


def test_subagent_prompt_encourages_multi_book() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Subagent should aim to draw from more than one book
    assert "more than one book" in prompt


def test_subagent_prompt_allows_multi_locate_in_large_books() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Large books like 清史稿 need multiple locate passes
    assert "multiple locate passes" in prompt or "several location steps" in prompt


def test_subagent_prompt_page_window_rule() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Should instruct subtasks to fetch multiple pages per locate call
    assert "page_no_end" in prompt
    assert "3" in prompt  # at least 3 pages at a time


def test_subagent_prompt_metadata_prefiler() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Should instruct subtasks to use time/category metadata before locate
    assert "时代" in prompt or "eras" in prompt.lower()
    assert "类别" in prompt or "categor" in prompt.lower()


def test_subagent_prompt_no_same_book_loop() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Should warn against looping on the same query/book
    assert "same query" in prompt and "same book" in prompt


def test_subagent_prompt_book_contribution_summary() -> None:
    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    # Output section should require a brief note on each book's contribution
    assert "各书的贡献" in prompt or "贡献或弃用理由" in prompt
