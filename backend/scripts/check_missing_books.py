#!/usr/bin/env python3
"""
对比 CSV 书目清单和 docs 目录，找出缺失的 PDF。

用法（在服务器上运行）:
    python3 scripts/check_missing_books.py --csv PDF文件列表.csv
    python3 scripts/check_missing_books.py --csv PDF文件列表.csv --docs /var/lib/history-rag/knowledge/docs
    python3 scripts/check_missing_books.py --csv PDF文件列表.csv --out missing.txt
"""

from __future__ import annotations

import argparse
import csv
import sys
import unicodedata
from pathlib import Path


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.strip())
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    return " ".join(text.split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, metavar="PATH", help="书目清单 CSV")
    parser.add_argument("--docs", default="/var/lib/history-rag/knowledge/docs",
                        metavar="DIR", help="PDF 所在目录")
    parser.add_argument("--out", metavar="FILE", help="将缺失列表写入文件")
    args = parser.parse_args()

    docs_dir = Path(args.docs)
    if not docs_dir.is_dir():
        print(f"目录不存在: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    # 读取已有 PDF（文件名去掉 .pdf 后 normalize）
    existing = {normalize(f.stem) for f in docs_dir.iterdir()
                if f.is_file() and f.suffix.lower() == ".pdf"}
    print(f"目录中已有 PDF: {len(existing)} 个", file=sys.stderr)

    # 读取 CSV（自动检测编码）
    titles: list[tuple[int, str]] = []
    for encoding in ("gb18030", "utf-8-sig", "utf-8"):
        try:
            with open(args.csv, encoding=encoding, newline="") as f:
                for row in csv.DictReader(f):
                    title = (row.get("书名") or "").strip()
                    try:
                        num = int((row.get("序号") or "").strip())
                    except ValueError:
                        continue
                    if title:
                        titles.append((num, title))
            break
        except UnicodeDecodeError:
            continue
    print(f"CSV 书目总数: {len(titles)} 本", file=sys.stderr)

    # 找缺失
    missing = [(num, title) for num, title in titles if normalize(title) not in existing]

    print(f"\n清单总数: {len(titles)}  已有: {len(titles) - len(missing)}  缺失: {len(missing)}\n")
    lines = [f"{num:4d}  {title}" for num, title in missing]
    print("\n".join(lines))

    if args.out:
        Path(args.out).write_text(
            f"缺失书目（共 {len(missing)} 本）\n\n" + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        print(f"\n已写入: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
