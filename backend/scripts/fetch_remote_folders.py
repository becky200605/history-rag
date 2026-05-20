#!/usr/bin/env python3
"""
Print the folder_path organisation of the local knowledge base.

Reads every *.pdf.json in <docs>/.ingestion/ and prints a tree
with document counts per folder.

Usage:
    python3 scripts/fetch_remote_folders.py
    python3 scripts/fetch_remote_folders.py --docs /var/lib/history-rag/knowledge/docs
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Show knowledge-base folder organisation.")
    parser.add_argument("--docs", default="/var/lib/history-rag/knowledge/docs", metavar="PATH")
    args = parser.parse_args()

    ingestion_dir = Path(args.docs) / ".ingestion"
    if not ingestion_dir.is_dir():
        print(f"Directory not found: {ingestion_dir}")
        return

    records: list[dict] = []
    for p in sorted(ingestion_dir.glob("*.pdf.json")):
        try:
            records.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"  [skip] {p.name}: {exc}")

    if not records:
        print("No ingestion records found.")
        return

    folder_map: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        folder = rec.get("folder_path") or "(未分类)"
        title = rec.get("display_title") or rec.get("source_filename") or "?"
        folder_map[folder].append(title)

    total = sum(len(v) for v in folder_map.values())
    print(f"共 {total} 本文档，{len(folder_map)} 个分类\n")
    for folder in sorted(folder_map):
        titles = sorted(folder_map[folder])
        print(f"📁 {folder}  ({len(titles)} 本)")
        for t in titles:
            print(f"   └─ {t}")
        print()


if __name__ == "__main__":
    main()
