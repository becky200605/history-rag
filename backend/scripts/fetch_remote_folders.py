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

    # Run Python on the server to emit a single JSON array — no parsing ambiguity
    remote_py = f"python3 -c \"import json,glob; print(json.dumps([json.load(open(f)) for f in glob.glob('{ingestion_dir}/*.pdf.json')]))\""
    cmd = ["ssh", args.host, remote_py]
    print(f"# Fetching folder structure from {args.host}:{ingestion_dir} …\n", flush=True)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"SSH error (rc={exc.returncode}):\n{exc.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("ssh not found in PATH", file=sys.stderr)
        sys.exit(1)

    raw = result.stdout.strip()
    if not raw:
        print("No ingestion records found.")
        return

    try:
        records: list[dict] = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse server response: {exc}\n{raw[:200]}", file=sys.stderr)
        sys.exit(1)

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
