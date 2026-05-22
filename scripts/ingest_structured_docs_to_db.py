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


def _insert_paragraphs(conn: sqlite3.Connection, doc_id: str, payload: dict) -> int:
    rows = []
    for page in payload.get("pages") or []:
        pdf_page_no = int(page.get("pdf_page_no") or page.get("page_no") or 1)
        page_no = int(page.get("page_no") or pdf_page_no)
        book_page_no = page.get("book_page_no")

        for para in page.get("paragraphs") or []:
            text = str(para.get("text") or "").strip()
            if not text:
                continue
            rows.append((
                doc_id,
                pdf_page_no,
                page_no,
                int(book_page_no) if book_page_no is not None else None,
                int(para.get("paragraph_no") or 1),
                int(para.get("paragraph_no_in_doc") or 1),
                str(para.get("paragraph_id") or f"page-{pdf_page_no}-p{para.get('paragraph_no', 1)}"),
                text,
            ))

    if rows:
        conn.executemany(
            """
            INSERT OR IGNORE INTO paragraphs
                (doc_id, pdf_page_no, page_no, book_page_no,
                 paragraph_no, paragraph_no_in_doc, paragraph_id, text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


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


def main(argv: list[str] | None = None) -> int:
    # 项目根目录 = 脚本所在目录的上一级
    project_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(description="把 .structured.json 增量写入 SQLite")
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=project_root / "knowledge" / "docs",
        help="知识库文档目录（默认: knowledge/docs）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "knowledge" / "paragraphs.db",
        help="目标 SQLite 文件（默认: knowledge/paragraphs.db）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会处理哪些文件，不写入 DB，不创建 .resolved 标记",
    )
    args = parser.parse_args(argv)

    docs_root: Path = args.docs_dir.resolve()
    db_path: Path = args.db.resolve()

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
        return 0 if failed == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
