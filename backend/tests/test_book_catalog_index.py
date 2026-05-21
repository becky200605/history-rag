"""Tests for the SQLite-backed book catalog persistent cache."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_entry(doc_id: str = "doc_1", scope: str = "global"):
    from src.community.knowledge_base.catalog import BookCatalogEntry

    return BookCatalogEntry(
        doc_id=doc_id,
        title="测试书目",
        filename=f"{doc_id}.txt",
        scope=scope,
        source_path=f"/fake/{doc_id}.txt",
        source_url=f"/api/knowledge/docs/{doc_id}.txt",
        original_url=None,
        preview="前八百字预览",
        search_text="测试书目 财政 历史",
        search_tokens=["测试", "书目", "财政", "历史"],
        type="core",
        categories=["财政史"],
        eras=["清代"],
        regions=["中国"],
        keywords=["税收"],
        summary="关于清代财政的研究",
        author="作者甲",
        publisher="出版社乙",
        priority=1,
        folder_path="财政/清代",
        language_hint="zh",
        page_count=350,
    )


@pytest.fixture()
def db_path(tmp_path: Path):
    """Patch get_paths() so the SQLite DB lands in a temp directory."""
    from unittest.mock import MagicMock

    paths_mock = MagicMock()
    paths_mock.knowledge_search_db_path.return_value = tmp_path / "test_catalog.sqlite3"
    paths_mock.ensure_knowledge_search_dirs.return_value = None

    with patch("src.community.knowledge_base.book_catalog_index.get_paths", return_value=paths_mock):
        yield tmp_path / "test_catalog.sqlite3"


class TestSaveAndLoad:
    def test_round_trip(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries = [_make_entry("a"), _make_entry("b", scope="thread")]
        save_catalog_to_db(thread_id="t1", user_id=None, mtime_sig=12345.0, entries=entries)
        loaded = load_catalog_from_db(thread_id="t1", user_id=None, mtime_sig=12345.0)

        assert loaded is not None
        assert len(loaded) == 2
        doc_ids = {e.doc_id for e in loaded}
        assert doc_ids == {"a", "b"}

    def test_metadata_survives_round_trip(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        original = _make_entry("meta_test")
        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1.0, entries=[original])
        loaded = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=1.0)

        assert loaded is not None
        entry = loaded[0]
        assert entry.title == "测试书目"
        assert entry.categories == ["财政史"]
        assert entry.eras == ["清代"]
        assert entry.keywords == ["税收"]
        assert entry.author == "作者甲"
        assert entry.page_count == 350
        assert entry.folder_path == "财政/清代"
        assert entry.language_hint == "zh"
        # search_tokens are recomputed from search_text on load — just verify they're non-empty
        # and consistent with what tokenize_search_text would produce.
        from src.community.knowledge_base.common import tokenize_search_text
        assert entry.search_tokens == tokenize_search_text(entry.search_text)

    def test_miss_when_empty(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db

        result = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=99.0)
        assert result is None

    def test_miss_when_mtime_differs(self, db_path: Path) -> None:
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=100.0, entries=[_make_entry()])
        result = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=999.0)
        assert result is None

    def test_cache_keys_are_independent(self, db_path: Path) -> None:
        """Different (thread_id, user_id) pairs do not interfere."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries_a = [_make_entry("for_thread_a")]
        entries_b = [_make_entry("for_thread_b")]
        save_catalog_to_db(thread_id="t_a", user_id=None, mtime_sig=1.0, entries=entries_a)
        save_catalog_to_db(thread_id="t_b", user_id=None, mtime_sig=2.0, entries=entries_b)

        loaded_a = load_catalog_from_db(thread_id="t_a", user_id=None, mtime_sig=1.0)
        loaded_b = load_catalog_from_db(thread_id="t_b", user_id=None, mtime_sig=2.0)

        assert loaded_a is not None and loaded_b is not None
        assert loaded_a[0].doc_id == "for_thread_a"
        assert loaded_b[0].doc_id == "for_thread_b"

    def test_overwrite_on_save(self, db_path: Path) -> None:
        """Saving again with a new mtime replaces old entries."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=1.0, entries=[_make_entry("old")])
        save_catalog_to_db(thread_id=None, user_id=None, mtime_sig=2.0, entries=[_make_entry("new")])

        # Old mtime no longer valid
        old = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=1.0)
        assert old is None

        # New mtime returns new entry only
        new = load_catalog_from_db(thread_id=None, user_id=None, mtime_sig=2.0)
        assert new is not None
        assert len(new) == 1
        assert new[0].doc_id == "new"

    def test_scope_ordering(self, db_path: Path) -> None:
        """Loaded entries are ordered thread → user → global."""
        from src.community.knowledge_base.book_catalog_index import load_catalog_from_db, save_catalog_to_db

        entries = [
            _make_entry("g", scope="global"),
            _make_entry("u", scope="user"),
            _make_entry("t", scope="thread"),
        ]
        save_catalog_to_db(thread_id="x", user_id="y", mtime_sig=1.0, entries=entries)
        loaded = load_catalog_from_db(thread_id="x", user_id="y", mtime_sig=1.0)

        assert loaded is not None
        scopes = [e.scope for e in loaded]
        assert scopes == ["thread", "user", "global"]


class TestListBookCatalogIntegration:
    """Verify list_book_catalog uses SQLite on the second cold call."""

    def test_sqlite_hit_avoids_file_rebuild(self, tmp_path: Path, db_path: Path) -> None:
        import src.community.knowledge_base.catalog as catalog_mod
        from unittest.mock import MagicMock

        with catalog_mod._catalog_cache_lock:
            catalog_mod._catalog_cache.clear()

        build_count = {"n": 0}

        def fake_build(*args, **kwargs):
            build_count["n"] += 1
            return [_make_entry("rebuilt")]

        paths_mock = MagicMock()
        paths_mock.knowledge_search_db_path.return_value = db_path
        paths_mock.ensure_knowledge_search_dirs.return_value = None

        fixed_mtime = 42.0

        with (
            patch.object(catalog_mod, "_build_global_entries", side_effect=fake_build),
            patch.object(catalog_mod, "_load_book_metadata_index", return_value={}),
            patch.object(catalog_mod, "get_knowledge_base_config", return_value=MagicMock(docs_path=str(tmp_path))),
            patch.object(catalog_mod, "resolve_project_path", return_value=tmp_path),
            patch.object(catalog_mod, "get_paths", return_value=MagicMock()),
            patch.object(catalog_mod, "_catalog_mtime_signature", return_value=fixed_mtime),
            patch("src.community.knowledge_base.book_catalog_index.get_paths", return_value=paths_mock),
        ):
            # First call: builds from files, writes to SQLite in background.
            result1 = catalog_mod.list_book_catalog()
            assert build_count["n"] == 1

            # Wait briefly for background SQLite write to complete.
            import time
            time.sleep(0.2)

            # Expire in-memory cache manually.
            with catalog_mod._catalog_cache_lock:
                catalog_mod._catalog_cache.clear()

            # Second call: should hit SQLite, NOT rebuild from files.
            result2 = catalog_mod.list_book_catalog()
            assert build_count["n"] == 1, "Should not rebuild — SQLite cache should be hit"
            assert len(result2) == 1
