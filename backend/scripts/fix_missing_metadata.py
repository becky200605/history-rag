#!/usr/bin/env python3
"""
找出本地 res/ 里缺少 folder_path 或 book-metadata 的书，重新生成 metadata 并上传到服务器。

判断标准（满足任一即需处理）：
  - ingestion record 的 folder_path 为空
  - .book-metadata/ 下没有对应的 sidecar 文件

前提：书必须已经 OCR 完成（parse_status = parsed，且存在 .structured.json）

用法：
    # 仅列出需要处理的书（不生成，不上传）
    python scripts/fix_missing_metadata.py --res ./res --config ../config.yaml --dry-run

    # 生成 metadata，不上传（先本地确认）
    python scripts/fix_missing_metadata.py --res ./res --config ../config.yaml --skip-upload

    # 生成并上传
    python scripts/fix_missing_metadata.py --res ./res --config ../config.yaml \\
        --host root@124.221.234.124

    # 指定模型，并发数
    python scripts/fix_missing_metadata.py --res ./res --config ../config.yaml \\
        --host root@124.221.234.124 --model deepseek-chat --concurrency 3
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _setup_config(config_path: str) -> None:
    from src.config.app_config import reload_app_config
    from src.config.knowledge_base_config import load_knowledge_base_config_from_dict
    app_config = reload_app_config(config_path)
    load_knowledge_base_config_from_dict(app_config.knowledge_base.model_dump())


# ---------------------------------------------------------------------------
# Metadata generation（复用 sync_to_server 的逻辑）
# ---------------------------------------------------------------------------

def _generate_metadata(filename: str, res_dir: Path, model_name: str | None) -> str | None:
    """生成 AI metadata，返回建议的 folder_path（失败返回 None）。"""
    from src.community.knowledge_base.book_metadata import get_book_metadata_dir
    from src.community.knowledge_base.book_metadata_runtime import generate_book_metadata_record
    from src.config.knowledge_base_config import BookMetadataConfig

    structured_path = res_dir / f"{filename}.structured.json"
    if not structured_path.exists():
        logger.warning("SKIP  %s  structured JSON 不存在", filename)
        return None

    try:
        structured_payload = json.loads(structured_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("SKIP  %s  读取 structured JSON 失败: %s", filename, exc)
        return None

    record_path = res_dir / f"{filename}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    title = str(record.get("display_title") or Path(filename).stem)

    get_book_metadata_dir(res_dir).mkdir(exist_ok=True)

    config = BookMetadataConfig(enabled=True, model_name=model_name)
    logger.info("META  %s  生成中...", filename)
    try:
        meta_record, _ = generate_book_metadata_record(
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
            summary = str(getattr(getattr(suggestion, "summary", None), "value", "") or "")[:80]
            logger.info("META  %s  folder=%s  %s...", filename, folder, summary)
        return folder
    except Exception as exc:
        logger.warning("META  %s  生成失败: %s", filename, exc)
        return None


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------

def _needs_processing(filename: str, res_dir: Path) -> tuple[bool, str]:
    """判断该书是否需要处理，返回 (需要处理, 原因)。"""
    from src.community.knowledge_base.book_metadata import derive_book_metadata_filename, get_book_metadata_dir

    record_path = res_dir / f"{filename}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "无法读取 ingestion record"

    if record.get("parse_status") != "parsed":
        return False, f"parse_status={record.get('parse_status')}，跳过"

    if not (res_dir / f"{filename}.structured.json").exists():
        return False, "structured JSON 不存在，跳过"

    reasons = []
    if not record.get("folder_path"):
        reasons.append("无 folder_path")

    meta_path = get_book_metadata_dir(res_dir) / derive_book_metadata_filename(filename)
    if not meta_path.exists():
        reasons.append("无 metadata sidecar")

    if reasons:
        return True, " + ".join(reasons)
    return False, "已有 metadata 和 folder_path"


def _scan(res_dir: Path) -> list[tuple[str, str]]:
    """返回 [(filename, 原因), ...] 需要处理的书列表。"""
    results = []
    for p in sorted(res_dir.glob("*.pdf.json")):
        filename = p.stem  # "book.pdf"
        needed, reason = _needs_processing(filename, res_dir)
        if needed:
            results.append((filename, reason))
    return results


# ---------------------------------------------------------------------------
# 处理单本书
# ---------------------------------------------------------------------------

def _process_one(
    filename: str,
    res_dir: Path,
    model_name: str | None,
    host: str | None,
    remote_docs: str,
) -> str:
    from src.community.knowledge_base.book_metadata import derive_book_metadata_filename, get_book_metadata_dir

    # 1. 生成 metadata
    folder_path = _generate_metadata(filename, res_dir, model_name)

    # 2. 把 folder_path 写回 ingestion record（仅当原来为空时）
    if folder_path:
        record_path = res_dir / f"{filename}.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if not record.get("folder_path"):
                record["folder_path"] = folder_path
                record_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                logger.info("REC   %s  folder_path 已写入", filename)
        except Exception as exc:
            logger.warning("REC   %s  写入 folder_path 失败: %s", filename, exc)

    # 3. 上传到服务器
    if host:
        meta_file = get_book_metadata_dir(res_dir) / derive_book_metadata_filename(filename)
        ingestion_file = res_dir / f"{filename}.json"

        if meta_file.exists():
            dst_meta = f"{host}:{remote_docs}/.book-metadata/"
            subprocess.run(["rsync", "-az", str(meta_file), dst_meta], check=True)
            logger.info("SYNC  %s  → .book-metadata/", filename)

        if ingestion_file.exists():
            dst_ingestion = f"{host}:{remote_docs}/.ingestion/"
            subprocess.run(["rsync", "-az", str(ingestion_file), dst_ingestion], check=True)
            logger.info("SYNC  %s  → .ingestion/", filename)

    return f"OK    {filename}  folder={folder_path}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="修复缺少 metadata/folder 的书并上传")
    parser.add_argument("--res", default="./res", metavar="DIR",
                        help="本地 res/ 目录（默认 ./res）")
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="config.yaml 路径（LLM 配置，不传则用默认模型）")
    parser.add_argument("--model", default=None, metavar="MODEL",
                        help="生成 metadata 用的模型（覆盖 config.yaml）")
    parser.add_argument("--host", default=None, metavar="USER@HOST",
                        help="服务器 SSH 地址，不传则只本地生成不上传")
    parser.add_argument("--remote-docs", default="/var/lib/history-rag/knowledge/docs",
                        metavar="PATH", help="服务器 docs 目录")
    parser.add_argument("--concurrency", type=int, default=3, metavar="N",
                        help="并发生成数（默认 3）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出需要处理的书，不生成不上传")
    parser.add_argument("--skip-upload", action="store_true",
                        help="只本地生成 metadata，不上传到服务器")
    args = parser.parse_args()

    res_dir = Path(args.res).expanduser().resolve()
    if not res_dir.is_dir():
        logger.error("res 目录不存在: %s", res_dir)
        sys.exit(1)

    # 扫描
    pending = _scan(res_dir)
    if not pending:
        logger.info("✅  所有已解析的书都有 metadata 和 folder_path，无需处理")
        return

    logger.info("需要处理: %d 本", len(pending))
    for filename, reason in pending:
        logger.info("  • %s  [%s]", filename, reason)

    if args.dry_run:
        return

    # 加载配置
    if args.config:
        try:
            _setup_config(args.config)
        except Exception as exc:
            logger.error("加载 config.yaml 失败: %s", exc)
            sys.exit(1)
    else:
        # 最小配置：只开启 metadata 生成
        from src.config.knowledge_base_config import load_knowledge_base_config_from_dict
        load_knowledge_base_config_from_dict({"enabled": True, "mineru": None})

    host = None if args.skip_upload else args.host

    # 确保服务器目录存在
    if host:
        dirs = f"{args.remote_docs}/.ingestion {args.remote_docs}/.book-metadata"
        subprocess.run(["ssh", host, f"mkdir -p {dirs}"], check=True)

    # 并发处理
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(_process_one, fn, res_dir, args.model, host, args.remote_docs): fn
            for fn, _ in pending
        }
        for fut in as_completed(futures):
            fn = futures[fut]
            try:
                logger.info(fut.result())
                ok += 1
            except Exception as exc:
                logger.error("FAIL  %s: %s", fn, exc)
                failed += 1

    logger.info("完成: %d 成功  %d 失败", ok, failed)


if __name__ == "__main__":
    main()
