#!/usr/bin/env python3
"""
Fetch remote server directory structure for docs root.

Usage:
    python scripts/fetch_remote_structure.py
    python scripts/fetch_remote_structure.py --host root@124.221.234.124 --remote-docs /var/lib/history-rag/knowledge/docs --depth 4
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Print remote docs directory structure.")
    parser.add_argument("--host", default="root@124.221.234.124", metavar="USER@HOST")
    parser.add_argument("--remote-docs", default="/var/lib/history-rag/knowledge/docs", metavar="PATH")
    parser.add_argument("--depth", type=int, default=4, metavar="N",
                        help="Max directory depth (default: 4)")
    parser.add_argument("--all", action="store_true",
                        help="Include hidden files/dirs (starting with .)")
    args = parser.parse_args()

    # Build find command
    find_cmd = f"find {args.remote_docs} -maxdepth {args.depth}"
    if not args.all:
        # Exclude hidden dirs but still show them at depth 1 (so .ingestion, .book-metadata are visible)
        find_cmd = (
            f"find {args.remote_docs} -maxdepth 1 | sort && "
            f"find {args.remote_docs} -mindepth 2 -maxdepth {args.depth} "
            r"-not -path '*/\.*' | sort"
        )

    cmd = ["ssh", args.host, find_cmd]
    print(f"# Fetching: {args.host}:{args.remote_docs}  (depth={args.depth})\n")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().splitlines()
        # Pretty-print as indented tree
        base = args.remote_docs.rstrip("/")
        for line in lines:
            rel = line[len(base):]
            if not rel:
                print(f"{base}/")
                continue
            rel = rel.lstrip("/")
            depth = rel.count("/")
            indent = "  " * depth
            name = rel.rsplit("/", 1)[-1]
            print(f"{indent}{name}")
    except subprocess.CalledProcessError as exc:
        print(f"SSH error (rc={exc.returncode}):\n{exc.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("ssh not found in PATH", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
