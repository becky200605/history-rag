#!/usr/bin/env python3
"""
Print the folder_path organisation of the local knowledge base,
and optionally write a .folders.json registry for use by sync_to_server.py.

Usage (on server):
    python3 scripts/fetch_remote_folders.py
    python3 scripts/fetch_remote_folders.py --docs /var/lib/history-rag/knowledge/docs

    # Also write/update the folder registry used by the AI metadata prompt:
    python3 scripts/fetch_remote_folders.py --write-registry
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Show knowledge-base folder organisation.")
    parser.add_argument("--docs", default="/var/lib/history-rag/knowledge/docs", metavar="PATH")
    parser.add_argument(
        "--write-registry",
        action="store_true",
        help="Write/update docs/.folders.json so sync_to_server.py can download it",
    )
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
        folder = rec.get("folder_path") or None
        title = rec.get("display_title") or rec.get("source_filename") or "?"
        folder_map[folder or "(未分类)"].append(title)

    # ── Print tree ────────────────────────────────────────────────────────────
    total = sum(len(v) for v in folder_map.values())
    print(f"共 {total} 本文档，{len(folder_map)} 个分类\n")
    for folder in sorted(folder_map):
        titles = sorted(folder_map[folder])
        print(f"📁 {folder}  ({len(titles)} 本)")
        for t in titles:
            print(f"   └─ {t}")
        print()

    # ── Write .folders.json registry ─────────────────────────────────────────
    if args.write_registry:
        registry_path = Path(args.docs) / ".folders.json"

        # Load existing entries to preserve timestamps
        existing: dict[str, dict] = {}
        if registry_path.exists():
            try:
                payload = json.loads(registry_path.read_text(encoding="utf-8"))
                for entry in payload.get("folders") or []:
                    if entry.get("path"):
                        existing[entry["path"]] = entry
            except Exception:
                pass

        # Collect all known folder paths (expand parent segments too)
        known_folders: set[str] = set()
        for folder in folder_map:
            if folder == "(未分类)":
                continue
            # Add the folder and all its parent paths
            parts = folder.split("/")
            for depth in range(1, len(parts) + 1):
                known_folders.add("/".join(parts[:depth]))

        now = _utc_now()
        entries: list[dict] = []
        for path in sorted(known_folders):
            if path in existing:
                entries.append(existing[path])
            else:
                entries.append({"path": path, "created_at": now, "updated_at": now})

        registry_path.write_text(
            json.dumps({"folders": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Wrote {len(entries)} folder paths to {registry_path}")


if __name__ == "__main__":
    main()
