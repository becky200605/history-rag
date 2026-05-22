#!/usr/bin/env python3
"""Incremental ingestion: 把 *.structured.json 的段落内容写入 SQLite。

每次运行只处理还没有 .resolved 标记的文件，已处理的直接跳过，
所以可以放进 CI/CD 每次构建时无脑执行。

用法:
    python scripts/ingest_structured_docs_to_db.py [--docs-dir PATH] [--db PATH] [--dry-run]

默认值（不传参数时）:
    --docs-dir  knowledge/docs          (相对于项目根目录)
    --db        knowledge/paragraphs.db (相对于项目根目录)
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 从 config.yaml 读 docs_path（和后端保持一致）
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_path(raw: str) -> Path:
    """把相对/绝对路径都解析成绝对路径（相对路径以项目根为基准）。"""
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _docs_path_from_config() -> Path:
    """读 config.yaml 里的 knowledge_base.docs_path，读不到就用默认值。"""
    for candidate in (PROJECT_ROOT / "config.yaml", PROJECT_ROOT / "backend" / "config.yaml"):
        if not candidate.exists():
            continue
        try:
            import yaml  # type: ignore[import]
            cfg = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            raw = (cfg.get("knowledge_base") or {}).get("docs_path")
            if raw:
                return _resolve_path(str(raw))
        except Exception:
            pass
    return PROJECT_ROOT / "knowledge" / "docs"


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

STRUCTURED_SUFFIX = ".structured.json"
RESOLVED_SUFFIX = ".resolved"

# ──────────────────────────────────────────────
# SQLite schema
# ──────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS books (
    doc_id      TEXT    PRIMARY KEY,
    title       TEXT    NOT NULL DEFAULT '',
    filename    TEXT    NOT NULL DEFAULT '',
    author      TEXT    NOT NULL DEFAULT '',
    publisher   TEXT    NOT NULL DEFAULT '',
    type        TEXT    NOT NULL DEFAULT 'unknown',
    page_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id              TEXT    NOT NULL REFERENCES books(doc_id) ON DELETE CASCADE,
    pdf_page_no         INTEGER NOT NULL,
    page_no             INTEGER NOT NULL,
    book_page_no        INTEGER,
    paragraph_no        INTEGER NOT NULL,
    paragraph_no_in_doc INTEGER NOT NULL,
    paragraph_id        TEXT    NOT NULL,
    text                TEXT    NOT NULL,
    UNIQUE(doc_id, paragraph_id)
);

CREATE INDEX IF NOT EXISTS idx_paragraphs_doc_id ON paragraphs(doc_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_page   ON paragraphs(doc_id, pdf_page_no);

CREATE VIRTUAL TABLE IF NOT EXISTS paragraph_fts USING fts5(
    search_text,
    doc_id      UNINDEXED,
    title       UNINDEXED,
    filename    UNINDEXED,
    page_no     UNINDEXED,
    pdf_page_no UNINDEXED,
    paragraph_no         UNINDEXED,
    paragraph_no_in_doc  UNINDEXED,
    text        UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
"""

# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA_SQL)
    return conn


def _doc_exists(conn: sqlite3.Connection, doc_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM books WHERE doc_id = ?", (doc_id,)).fetchone()
    return row is not None


def _insert_book(conn: sqlite3.Connection, doc_id: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO books (doc_id, title, filename, page_count, indexed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            str(payload.get("title") or ""),
            str(payload.get("source_filename") or ""),
            len(payload.get("pages") or []),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _tokenize_for_fts(text: str) -> str:
    """简单分词：去标点，空格分隔，中文字符保留。"""
    import re
    # 保留中文、字母、数字，其余替换为空格
    cleaned = re.sub(r"[^一-鿿\w]", " ", text, flags=re.UNICODE)
    return " ".join(cleaned.split())


def _insert_paragraphs(conn: sqlite3.Connection, doc_id: str, payload: dict) -> int:
    title = str(payload.get("title") or "")
    filename = str(payload.get("source_filename") or "")

    para_rows = []
    fts_rows = []

    for page in payload.get("pages") or []:
        pdf_page_no = int(page.get("pdf_page_no") or page.get("page_no") or 1)
        page_no = int(page.get("page_no") or pdf_page_no)
        book_page_no = page.get("book_page_no")

        for para in page.get("paragraphs") or []:
            text = str(para.get("text") or "").strip()
            if not text:
                continue
            paragraph_no = int(para.get("paragraph_no") or 1)
            paragraph_no_in_doc = int(para.get("paragraph_no_in_doc") or 1)
            paragraph_id = str(para.get("paragraph_id") or f"page-{pdf_page_no}-p{paragraph_no}")

            para_rows.append((
                doc_id,
                pdf_page_no,
                page_no,
                int(book_page_no) if book_page_no is not None else None,
                paragraph_no,
                paragraph_no_in_doc,
                paragraph_id,
                text,
            ))
            fts_rows.append((
                _tokenize_for_fts(text),
                doc_id,
                title,
                filename,
                page_no,
                pdf_page_no,
                paragraph_no,
                paragraph_no_in_doc,
                text,
            ))

    if para_rows:
        conn.executemany(
            """
            INSERT OR IGNORE INTO paragraphs
                (doc_id, pdf_page_no, page_no, book_page_no,
                 paragraph_no, paragraph_no_in_doc, paragraph_id, text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            para_rows,
        )
    if fts_rows:
        # 先删旧的，再写新的（保证重跑幂等）
        conn.execute("DELETE FROM paragraph_fts WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            """
            INSERT INTO paragraph_fts
                (search_text, doc_id, title, filename,
                 page_no, pdf_page_no, paragraph_no, paragraph_no_in_doc, text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
    return len(para_rows)


# ──────────────────────────────────────────────
# doc_id 计算（和 catalog.py 保持一致）
# ──────────────────────────────────────────────


def derive_doc_id(docs_root: Path, structured_path: Path) -> str:
    """从 .structured.json 路径还原出对应源文件的 doc_id。

    doc_id = 源文件相对于 docs_root 的 POSIX 路径
    例如：docs_root/子目录/历史书.pdf.structured.json
         → "子目录/历史书.pdf"
    """
    # 去掉 .structured.json 后缀，得到源文件路径
    name = structured_path.name
    if name.endswith(STRUCTURED_SUFFIX):
        source_name = name[: -len(STRUCTURED_SUFFIX)]
    else:
        source_name = name

    source_path = structured_path.parent / source_name
    try:
        return source_path.resolve().relative_to(docs_root.resolve()).as_posix()
    except ValueError:
        return source_name


# ──────────────────────────────────────────────
# 主逻辑
# ──────────────────────────────────────────────


def find_pending_files(docs_root: Path) -> list[Path]:
    """返回所有没有 .resolved 标记的 .structured.json 文件。"""
    pending = []
    for path in sorted(docs_root.rglob(f"*{STRUCTURED_SUFFIX}")):
        resolved_marker = path.with_suffix(path.suffix + RESOLVED_SUFFIX)
        if not resolved_marker.exists():
            pending.append(path)
    return pending


def ingest_file(
    conn: sqlite3.Connection,
    docs_root: Path,
    structured_path: Path,
    *,
    dry_run: bool = False,
) -> bool:
    """处理单个 .structured.json 文件，返回是否成功。"""
    try:
        payload = json.loads(structured_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取失败，跳过 %s: %s", structured_path, exc)
        return False

    doc_id = derive_doc_id(docs_root, structured_path)
    title = str(payload.get("title") or doc_id)
    page_count = len(payload.get("pages") or [])

    if dry_run:
        logger.info("[dry-run] 会入库: %s  (title=%r, pages=%d)", doc_id, title, page_count)
        return True

    try:
        with conn:
            _insert_book(conn, doc_id, payload)
            para_count = _insert_paragraphs(conn, doc_id, payload)

        # 打标记：在同目录创建 <filename>.resolved
        marker = structured_path.with_suffix(structured_path.suffix + RESOLVED_SUFFIX)
        marker.write_text(
            f"ingested_at={datetime.now(timezone.utc).isoformat()}\ndoc_id={doc_id}\n",
            encoding="utf-8",
        )
        logger.info("✓  %s  (pages=%d, paragraphs=%d)", doc_id, page_count, para_count)
        return True
    except Exception as exc:
        logger.error("入库失败 %s: %s", doc_id, exc)
        return False


def _print_status(conn: sqlite3.Connection, db_path: Path) -> None:
    total_books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    total_paras = conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
    print(f"\nDB 路径: {db_path}")
    print(f"书目总数: {total_books}")
    print(f"段落总数: {total_paras:,}")

    if total_books == 0:
        print("（库里还没有数据）")
        return

    print("\n── 各书段落数 / 页数（前 20 条）──")
    rows = conn.execute(
        """
        SELECT b.doc_id, b.title, b.page_count,
               COUNT(p.id) AS para_count
        FROM books b
        LEFT JOIN paragraphs p ON p.doc_id = b.doc_id
        GROUP BY b.doc_id
        ORDER BY para_count DESC
        LIMIT 20
        """
    ).fetchall()
    for r in rows:
        print(f"  [{r['para_count']:>5} 段 / {r['page_count']:>4} 页]  {r['title'] or r['doc_id']}")

    print("\n提示: 用 --sample <doc_id> 查看某本书的具体段落内容")


def _print_sample(conn: sqlite3.Connection, doc_id: str) -> None:
    book = conn.execute("SELECT * FROM books WHERE doc_id = ?", (doc_id,)).fetchone()
    if not book:
        # 尝试模糊匹配 title
        book = conn.execute(
            "SELECT * FROM books WHERE title LIKE ?", (f"%{doc_id}%",)
        ).fetchone()
    if not book:
        print(f"找不到 doc_id 或 title 包含 '{doc_id}' 的书，用 --status 查看所有书目")
        return

    real_doc_id = book["doc_id"]
    print(f"\n书名: {book['title']}")
    print(f"doc_id: {real_doc_id}")
    print(f"页数: {book['page_count']}  indexed_at: {book['indexed_at']}")

    rows = conn.execute(
        """
        SELECT pdf_page_no, page_no, paragraph_no_in_doc, text
        FROM paragraphs
        WHERE doc_id = ?
        ORDER BY paragraph_no_in_doc
        LIMIT 3
        """,
        (real_doc_id,),
    ).fetchall()
    print(f"\n── 前 {len(rows)} 段内容 ──")
    for r in rows:
        print(f"\n  [doc段落#{r['paragraph_no_in_doc']}  PDF页{r['pdf_page_no']}  书页{r['page_no']}]")
        print(f"  {r['text'][:200]}{'…' if len(r['text']) > 200 else ''}")


def _prewarm_indexes() -> None:
    """入库完成后同步重建 catalog SQLite 缓存和 FTS 全文索引，替代独立的 prewarm 脚本。"""
    import json as _json
    import sys as _sys

    backend_root = PROJECT_ROOT / "backend"
    if str(backend_root) not in _sys.path:
        _sys.path.insert(0, str(backend_root))

    try:
        from src.config.app_config import get_app_config
        get_app_config()
    except Exception as exc:
        logger.warning("prewarm: 无法加载 app config，跳过索引重建: %s", exc)
        return

    # 1. Book catalog SQLite cache
    try:
        import time
        from src.community.knowledge_base.book_catalog_index import save_catalog_to_db
        from src.community.knowledge_base.catalog import _catalog_mtime_signature, list_book_catalog
        from src.community.knowledge_base.common import resolve_project_path
        from src.config.knowledge_base_config import get_knowledge_base_config

        docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
        logger.info("[prewarm] 重建 book catalog 缓存...")
        t0 = time.perf_counter()
        entries = list_book_catalog(thread_id=None, user_id=None, include_search_content=True, caller="ingest_prewarm")
        mtime_sig = _catalog_mtime_signature(docs_root, None, None)
        save_catalog_to_db(None, None, mtime_sig, entries)
        logger.info("[prewarm] catalog 缓存完成: %d 条，耗时 %.1fs", len(entries), time.perf_counter() - t0)
    except Exception as exc:
        logger.warning("[prewarm] catalog 缓存失败（不影响运行）: %s", exc)

    # 2. Keyword FTS index
    try:
        import time
        from src.community.knowledge_base.common import derive_global_doc_id, resolve_project_path
        from src.community.knowledge_base.keyword_search_index import ensure_documents_indexed, resolve_documents_for_doc_ids
        from src.config.knowledge_base_config import get_knowledge_base_config

        docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
        ingestion_dir = docs_root / ".ingestion"
        if not ingestion_dir.exists():
            return

        doc_ids = []
        for record_path in sorted(ingestion_dir.glob("*.json")):
            try:
                record = _json.loads(record_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("schema_version") == 1:
                continue
            source_filename = str(record.get("source_filename") or "")
            if source_filename and record.get("indexable"):
                doc_ids.append(derive_global_doc_id(docs_root, docs_root / source_filename))

        if not doc_ids:
            return

        logger.info("[prewarm] 重建 FTS 索引: %d 本书...", len(doc_ids))
        t0 = time.perf_counter()
        documents = resolve_documents_for_doc_ids(thread_id=None, user_id=None, doc_ids=doc_ids)
        ensure_documents_indexed(documents)
        logger.info("[prewarm] FTS 索引完成: %d 本，耗时 %.1fs", len(documents), time.perf_counter() - t0)
    except Exception as exc:
        logger.warning("[prewarm] FTS 索引失败（不影响运行）: %s", exc)


def main(argv: list[str] | None = None) -> int:
    default_docs_dir = _docs_path_from_config()
    default_db = default_docs_dir.parent / "paragraphs.db"

    parser = argparse.ArgumentParser(description="把 .structured.json 增量写入 SQLite")
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=default_docs_dir,
        help=f"知识库文档目录（默认从 config.yaml 读取，当前: {default_docs_dir}）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db,
        help=f"目标 SQLite 文件（默认与 docs-dir 同级，当前: {default_db}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会处理哪些文件，不写入 DB，不创建 .resolved 标记",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看 DB 现有数据概览，不做任何写入",
    )
    parser.add_argument(
        "--sample",
        metavar="DOC_ID",
        help="打印指定 doc_id 的前 3 段内容，用于验证入库正确性",
    )
    args = parser.parse_args(argv)

    docs_root: Path = args.docs_dir.resolve()
    db_path: Path = args.db.resolve()

    if args.status or args.sample:
        if not db_path.exists():
            print(f"DB 文件不存在: {db_path}")
            return 1
        conn = _connect(db_path)
        try:
            if args.status:
                _print_status(conn, db_path)
            if args.sample:
                _print_sample(conn, args.sample)
        finally:
            conn.close()
        return 0

    if not docs_root.exists():
        logger.error("docs-dir 不存在: %s", docs_root)
        return 1

    pending = find_pending_files(docs_root)
    if not pending:
        logger.info("没有待处理的文件，全部已标记为 .resolved，退出。")
        return 0

    logger.info("发现 %d 个待处理文件，DB: %s", len(pending), db_path)

    if args.dry_run:
        for p in pending:
            ingest_file(None, docs_root, p, dry_run=True)  # type: ignore[arg-type]
        return 0

    conn = _connect(db_path)
    try:
        ok = sum(ingest_file(conn, docs_root, p) for p in pending)
        failed = len(pending) - ok
        logger.info("完成: 成功 %d，失败 %d", ok, failed)
    finally:
        conn.close()

    if ok > 0:
        _prewarm_indexes()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
