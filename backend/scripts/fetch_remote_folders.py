#!/usr/bin/env python3
"""
Fetch the folder_path organisation of the remote knowledge base.

Reads every *.pdf.json in <remote-docs>/.ingestion/, collects all
folder_path values, and prints a tree with document counts.

Usage:
    python scripts/fetch_remote_folders.py
    python scripts/fetch_remote_folders.py --host root@124.221.234.124 \
        --remote-docs /var/lib/history-rag/knowledge/docs
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict


def main() -> None:
    parser = argparse.ArgumentParser(description="Show knowledge-base folder organisation.")
    parser.add_argument("--host", default="root@124.221.234.124", metavar="USER@HOST")
    parser.add_argument("--remote-docs", default="/var/lib/history-rag/knowledge/docs", metavar="PATH")
    args = parser.parse_args()

    ingestion_dir = f"{args.remote_docs}/.ingestion"

    # Pull every *.pdf.json from the server in one SSH call
    cmd = ["ssh", args.host,
           f"find {ingestion_dir} -maxdepth 1 -name '*.pdf.json' -exec cat {{}} \\;"]
    print(f"# Fetching folder structure from {args.host}:{ingestion_dir} …\n", flush=True)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"SSH error (rc={exc.returncode}):\n{exc.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("ssh not found in PATH", file=sys.stderr)
        sys.exit(1)

    # The output is a stream of concatenated JSON objects — split on "}\n{"
    raw = result.stdout.strip()
    if not raw:
        print("No ingestion records found.")
        return

    # Parse records one by one (each file is a single JSON object on its own)
    records: list[dict] = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(raw):
        try:
            obj, offset = decoder.raw_decode(raw, pos)
            records.append(obj)
            pos += offset
            # skip whitespace between records
            while pos < len(raw) and raw[pos] in " \t\n\r":
                pos += 1
        except json.JSONDecodeError:
            pos += 1

    # Collect folder_path → list of display_title
    folder_map: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        folder = rec.get("folder_path") or "(未分类)"
        title = rec.get("display_title") or rec.get("source_filename") or "?"
        folder_map[folder].append(title)

    # Print tree
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
