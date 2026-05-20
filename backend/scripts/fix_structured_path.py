"""
批量修复全局知识库 ingestion record 中 structured_path 为 null 的问题。

对每条 structured_path=null 但 structured_filename 有值的 record，
在 docs_root 下查找对应文件并补全 structured_path。

用法（在 backend/ 目录下运行）：
    uv run python scripts/fix_structured_path.py
    uv run python scripts/fix_structured_path.py --dry-run
"""

import argparse
import json
from pathlib import Path


def find_structured_file(docs_root: Path, structured_filename: str) -> Path | None:
    """在 docs_root 下搜索 structured_filename，返回第一个匹配的绝对路径。"""
    # 优先在 .ingestion/ 下找（最常见位置）
    candidate = docs_root / ".ingestion" / structured_filename
    if candidate.exists():
        return candidate.resolve()

    # 在 docs_root 根目录找
    candidate = docs_root / structured_filename
    if candidate.exists():
        return candidate.resolve()

    # 递归搜索（兜底，较慢）
    for match in docs_root.rglob(structured_filename):
        return match.resolve()

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="修复全局知识库 ingestion record 的 structured_path")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    parser.add_argument(
        "--docs-root",
        default="/var/lib/history-rag/knowledge/docs",
        help="知识库文档根目录（默认: /var/lib/history-rag/knowledge/docs）",
    )
    args = parser.parse_args()

    docs_root = Path(args.docs_root).resolve()
    ingestion_dir = docs_root / ".ingestion"

    if not ingestion_dir.exists():
        print(f"ingestion 目录不存在: {ingestion_dir}")
        return

    total = fixed = skipped = missing = 0

    for record_path in sorted(ingestion_dir.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[SKIP] 读取失败 {record_path.name}: {e}")
            continue

        if record.get("schema_version") == 1:
            continue

        total += 1

        if record.get("structured_path"):
            skipped += 1
            continue

        structured_filename = record.get("structured_filename") or record.get("index_target_filename")
        if not structured_filename:
            print(f"[SKIP] 无 structured_filename: {record_path.name}")
            skipped += 1
            continue

        found = find_structured_file(docs_root, structured_filename)
        if not found:
            print(f"[MISS] 文件未找到: {structured_filename}  ({record_path.name})")
            missing += 1
            continue

        print(f"[FIX{'(dry)' if args.dry_run else ''}] {record_path.name}")
        print(f"       structured_path -> {found}")

        if not args.dry_run:
            record["structured_path"] = str(found)
            record["index_target_path"] = str(found)
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        fixed += 1

    print(f"\n完成: 共 {total} 条，修复 {fixed} 条，跳过 {skipped} 条，文件缺失 {missing} 条")
    if args.dry_run:
        print("（dry-run 模式，未实际写入）")


if __name__ == "__main__":
    main()
