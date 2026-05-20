#!/usr/bin/env python3
"""
Print the folder_path organisation of the local knowledge base,
and optionally write a .folders.json registry for use by sync_to_server.py.

Usage (on server):
    python3 scripts/fetch_remote_folders.py
    python3 scripts/fetch_remote_folders.py --docs /var/lib/history-rag/knowledge/docs

    # Refresh the registry (preserves empty folders, respects user deletions):
    python3 scripts/fetch_remote_folders.py --write-registry

    # Bootstrap: populate registry from ingestion records (first-time setup only):
    python3 scripts/fetch_remote_folders.py --write-registry --sync-from-records

IMPORTANT: --write-registry without --sync-from-records treats the registry as the
source of truth.  Folders the user deleted via the UI will NOT be re-added even if
ingestion records still reference them.  Use --sync-from-records only when
bootstrapping a fresh registry from scratch.
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
    parser.add_argument(
        "--sync-from-records",
        action="store_true",
        help=(
            "When writing the registry, also add folders inferred from ingestion records "
            "that are not yet in the registry. Use only for initial bootstrap — "
            "by default the registry is treated as the source of truth and deleted "
            "folders are NOT re-added from ingestion records."
        ),
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

        # Start from all existing entries (preserves empty folders + timestamps)
        existing: dict[str, dict] = {}
        if registry_path.exists():
            try:
                payload = json.loads(registry_path.read_text(encoding="utf-8"))
                for entry in payload.get("folders") or []:
                    if entry.get("path"):
                        existing[entry["path"]] = entry
            except Exception:
                pass

        # Optionally add folders inferred from ingestion records.
        # Only done when --sync-from-records is set (bootstrap / first-time setup).
        # By default the registry is the source of truth: folders the user deleted
        # must NOT be resurrected just because a book still carries that folder_path.
        now = _utc_now()
        if args.sync_from_records:
            for folder in folder_map:
                if folder == "(未分类)":
                    continue
                parts = folder.split("/")
                for depth in range(1, len(parts) + 1):
                    path = "/".join(parts[:depth])
                    if path not in existing:
                        existing[path] = {"path": path, "created_at": now, "updated_at": now}
        else:
            # Report folders in ingestion records that are absent from the registry
            # so the operator knows which books are "orphaned" without silently fixing it.
            orphaned: list[str] = []
            for folder in folder_map:
                if folder == "(未分类)":
                    continue
                parts = folder.split("/")
                for depth in range(1, len(parts) + 1):
                    path = "/".join(parts[:depth])
                    if path not in existing:
                        orphaned.append(path)
                        break  # only report the deepest missing segment per book-folder
            if orphaned:
                unique_orphaned = sorted(set(orphaned))
                print(
                    f"⚠️  {len(unique_orphaned)} folder(s) appear in ingestion records but are absent from "
                    f"the registry (add --sync-from-records to include them):"
                )
                for p in unique_orphaned:
                    print(f"   • {p}")

        entries = sorted(existing.values(), key=lambda e: e["path"])
        registry_path.write_text(
            json.dumps({"folders": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Wrote {len(entries)} folder paths to {registry_path} (including empty folders)")


if __name__ == "__main__":
    main()
