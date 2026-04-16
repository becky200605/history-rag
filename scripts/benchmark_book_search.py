#!/usr/bin/env python3
"""Benchmark the book_search pipeline for a single query.

Example:
    python3 scripts/benchmark_book_search.py --query "盛宣怀 生平"
    python3 scripts/benchmark_book_search.py --query "盛宣怀 生平" --runs 3
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.config.knowledge_base_config import load_knowledge_base_config_from_dict


@dataclass
class TimingProbe:
    name: str
    call_count: int = 0
    total_seconds: float = 0.0
    samples: list[float] = field(default_factory=list)

    def record(self, elapsed: float) -> None:
        self.call_count += 1
        self.total_seconds += elapsed
        self.samples.append(elapsed)

    @property
    def average_seconds(self) -> float:
        if not self.samples:
            return 0.0
        return self.total_seconds / len(self.samples)


@dataclass
class BenchmarkResult:
    list_seconds: float
    list_count: int
    search_seconds: float
    search_count: int
    tool_seconds: float
    tool_output_chars: int
    tool_output_lines: int
    probes: dict[str, TimingProbe]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the book_search tool.")
    parser.add_argument("--query", default="盛宣怀 生平", help="Query passed to book_search.")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs to execute.")
    parser.add_argument("--top-k", type=int, default=20, help="Top-k for direct catalog search.")
    parser.add_argument("--thread-id", default=None, help="Optional thread_id context.")
    parser.add_argument("--user-id", default=None, help="Optional user_id context.")
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config.yaml"),
        help="Path to config.yaml.",
    )
    return parser.parse_args()


def _load_env_files() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)
    load_dotenv(override=False)


def _resolve_value_leniently(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            inner = value[2:-1]
            if ":-" in inner:
                env_name, default_value = inner.split(":-", 1)
                resolved = os.getenv(env_name)
                if resolved is not None:
                    return resolved
                if default_value in {"null", "None", "~"}:
                    return None
                return default_value
            return os.getenv(inner)
        if value.startswith("$") and len(value) > 1:
            return os.getenv(value[1:])
        return value
    if isinstance(value, dict):
        return {key: _resolve_value_leniently(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value_leniently(item) for item in value]
    return value


def _load_knowledge_base_config(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}
    knowledge_base_config = _resolve_value_leniently(raw_config.get("knowledge_base", {}))
    if isinstance(knowledge_base_config, dict):
        # The benchmark only exercises book catalog search. Optional runtime
        # integrations such as MinerU / translation gRPC are irrelevant here,
        # and many local environments leave those env vars unset.
        for optional_section in ("mineru", "translation_rpc"):
            section_value = knowledge_base_config.get(optional_section)
            if isinstance(section_value, dict) and any(value is None for value in section_value.values()):
                knowledge_base_config.pop(optional_section, None)
    load_knowledge_base_config_from_dict(knowledge_base_config)


def _time_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    started = perf_counter()
    result = fn(*args, **kwargs)
    return result, perf_counter() - started


@contextmanager
def _instrument_book_search() -> Iterator[dict[str, TimingProbe]]:
    from src.community.knowledge_base import catalog as catalog_module
    from src.community.knowledge_base import tools as tools_module

    probes: dict[str, TimingProbe] = {}
    originals: list[tuple[object, str, Callable[..., Any]]] = []

    def wrap(module: object, attr_name: str, probe_name: str) -> None:
        original = getattr(module, attr_name)
        originals.append((module, attr_name, original))
        probe = probes.setdefault(probe_name, TimingProbe(name=probe_name))

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                probe.record(perf_counter() - started)

        setattr(module, attr_name, wrapped)

    wrap(tools_module, "list_book_catalog", "tools.list_book_catalog")
    wrap(catalog_module, "list_book_catalog", "catalog.list_book_catalog")
    wrap(catalog_module, "_load_book_metadata_index", "catalog._load_book_metadata_index")
    wrap(catalog_module, "_build_global_entries", "catalog._build_global_entries")
    wrap(catalog_module, "_read_preview", "catalog._read_preview")
    wrap(catalog_module, "_read_structured_preview", "catalog._read_structured_preview")
    wrap(catalog_module, "_read_structured_search_excerpt", "catalog._read_structured_search_excerpt")

    try:
        yield probes
    finally:
        for module, attr_name, original in reversed(originals):
            setattr(module, attr_name, original)


def _run_once(
    *,
    query: str,
    thread_id: str | None,
    user_id: str | None,
    top_k: int,
) -> BenchmarkResult:
    from src.community.knowledge_base import catalog as catalog_module
    from src.community.knowledge_base import tools as tools_module

    runtime = SimpleNamespace(context={})
    if thread_id:
        runtime.context["thread_id"] = thread_id
    if user_id:
        runtime.context["user_id"] = user_id

    tool_callable = getattr(tools_module.book_search_tool, "func", tools_module.book_search_tool)

    entries, list_seconds = _time_call(
        catalog_module.list_book_catalog,
        thread_id=thread_id,
        user_id=user_id,
    )
    candidates, search_seconds = _time_call(
        catalog_module.search_book_catalog,
        query,
        thread_id=thread_id,
        user_id=user_id,
        top_k=top_k,
    )

    with _instrument_book_search() as probes:
        tool_output, tool_seconds = _time_call(tool_callable, runtime, query)

    return BenchmarkResult(
        list_seconds=list_seconds,
        list_count=len(entries),
        search_seconds=search_seconds,
        search_count=len(candidates),
        tool_seconds=tool_seconds,
        tool_output_chars=len(tool_output),
        tool_output_lines=len(tool_output.splitlines()),
        probes=probes,
    )


def _format_probe(probe: TimingProbe) -> str:
    return (
        f"{probe.name}: calls={probe.call_count}, "
        f"total={probe.total_seconds:.3f}s, "
        f"avg={probe.average_seconds:.3f}s"
    )


def _print_run(index: int, result: BenchmarkResult) -> None:
    print(f"Run {index}")
    print(
        f"  list_book_catalog: {result.list_seconds:.3f}s "
        f"({result.list_count} entries)"
    )
    print(
        f"  search_book_catalog: {result.search_seconds:.3f}s "
        f"({result.search_count} candidates)"
    )
    print(
        f"  book_search_tool: {result.tool_seconds:.3f}s "
        f"({result.tool_output_lines} lines, {result.tool_output_chars} chars)"
    )
    print("  instrumentation:")
    for probe_name in sorted(result.probes):
        print(f"    - {_format_probe(result.probes[probe_name])}")
    tools_calls = result.probes.get("tools.list_book_catalog", TimingProbe("tools.list_book_catalog")).call_count
    catalog_calls = result.probes.get("catalog.list_book_catalog", TimingProbe("catalog.list_book_catalog")).call_count
    if tools_calls + catalog_calls >= 2:
        print("    - observation: the tool path rebuilt the book catalog more than once in this run.")


def _print_summary(results: list[BenchmarkResult]) -> None:
    def average(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    print("\nSummary")
    print(f"  avg list_book_catalog: {average([item.list_seconds for item in results]):.3f}s")
    print(f"  avg search_book_catalog: {average([item.search_seconds for item in results]):.3f}s")
    print(f"  avg book_search_tool: {average([item.tool_seconds for item in results]):.3f}s")


def main() -> int:
    args = _parse_args()
    _load_env_files()
    _load_knowledge_base_config(args.config)

    print("book_search benchmark")
    print(f"  config: {args.config}")
    print(f"  query: {args.query}")
    print(f"  runs: {args.runs}")
    print(f"  thread_id: {args.thread_id or '-'}")
    print(f"  user_id: {args.user_id or '-'}")

    results: list[BenchmarkResult] = []
    for index in range(1, args.runs + 1):
        result = _run_once(
            query=args.query,
            thread_id=args.thread_id,
            user_id=args.user_id,
            top_k=args.top_k,
        )
        results.append(result)
        _print_run(index, result)

    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
