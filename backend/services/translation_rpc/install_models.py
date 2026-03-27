"""Install Argos Translate language packages for the standalone translation RPC service."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from translation_runtime import ensure_language_pair_installed
else:
    from .translation_runtime import ensure_language_pair_installed

DEFAULT_PAIRS = ("en:zh", "ja:zh", "ko:zh")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Argos Translate language packages.")
    parser.add_argument(
        "--pair",
        action="append",
        dest="pairs",
        help="Language pair to install in source:target form, for example en:zh.",
    )
    return parser.parse_args()


def _parse_pair(value: str) -> tuple[str, str]:
    source, separator, target = value.partition(":")
    source = source.strip()
    target = target.strip()
    if not separator or not source or not target:
        raise ValueError(f"Invalid language pair: {value}")
    return source, target


def main() -> None:
    args = _parse_args()
    pairs = args.pairs or list(DEFAULT_PAIRS)
    for raw_pair in pairs:
        source_language, target_language = _parse_pair(raw_pair)
        print(f"Installing Argos package for {source_language}->{target_language}...")
        ensure_language_pair_installed(source_language, target_language)
        print(f"Installed Argos package for {source_language}->{target_language}")


if __name__ == "__main__":
    main()
