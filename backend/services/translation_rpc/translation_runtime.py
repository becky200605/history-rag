"""Standalone translation runtime for the translation RPC service."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_TARGET_LANGUAGE = "zh"
DEFAULT_SOURCE_LANGUAGE = "en"
PIVOT_LANGUAGES = ("en",)


def _normalize_code(code: str | None) -> str:
    value = str(code or "").strip().lower()
    if not value:
        return ""
    return value.replace("-", "_")


def _language_prefix(code: str) -> str:
    normalized = _normalize_code(code)
    return normalized.split("_", 1)[0] if normalized else ""


def _load_argos_modules():
    try:
        from argostranslate import package as argos_package
        from argostranslate import translate as argos_translate
    except ImportError as exc:
        raise RuntimeError(
            "argostranslate is not installed. Install the service dependencies first."
        ) from exc
    return argos_package, argos_translate


def normalize_translation_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(block.get("id") or "").strip(),
            "text": str(block.get("text") or "").strip(),
        }
        for block in blocks
        if str(block.get("id") or "").strip() and str(block.get("text") or "").strip()
    ]


def detect_source_language(text: str, default_source_language: str = DEFAULT_SOURCE_LANGUAGE) -> str:
    normalized = text.strip()
    if not normalized:
        return _normalize_code(default_source_language)

    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", normalized))
    kana_count = len(re.findall(r"[\u3040-\u30ff]", normalized))
    hangul_count = len(re.findall(r"[\uac00-\ud7af]", normalized))
    cyrillic_count = len(re.findall(r"[\u0400-\u04ff]", normalized))
    latin_count = len(re.findall(r"[A-Za-z]", normalized))

    if cjk_count >= max(4, len(normalized) // 10) and kana_count == 0:
        return "zh"
    if kana_count > 0:
        return "ja"
    if hangul_count > 0:
        return "ko"
    if cyrillic_count > 0:
        return "ru"
    if latin_count > 0:
        return _normalize_code(default_source_language) or DEFAULT_SOURCE_LANGUAGE
    return _normalize_code(default_source_language) or DEFAULT_SOURCE_LANGUAGE


def _should_auto_install_models() -> bool:
    return (os.getenv("TRANSLATION_RPC_AUTO_INSTALL") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _find_installed_language(code: str):
    _, argos_translate = _load_argos_modules()
    normalized = _normalize_code(code)
    prefix = _language_prefix(normalized)
    installed_languages = argos_translate.get_installed_languages()

    for language in installed_languages:
        if _normalize_code(getattr(language, "code", "")) == normalized:
            return language
    for language in installed_languages:
        if _language_prefix(getattr(language, "code", "")) == prefix:
            return language
    return None


def _find_available_package(available_packages, source_language: str, target_language: str):
    source_prefix = _language_prefix(source_language)
    target_prefix = _language_prefix(target_language)
    for package in available_packages:
        package_source = _language_prefix(getattr(package, "from_code", ""))
        package_target = _language_prefix(getattr(package, "to_code", ""))
        if package_source == source_prefix and package_target == target_prefix:
            return package
    return None


def _download_and_install_package(package) -> None:
    argos_package, _ = _load_argos_modules()
    download_path = Path(package.download())
    try:
        argos_package.install_from_path(str(download_path))
    finally:
        if download_path.exists():
            download_path.unlink(missing_ok=True)


def _install_language_pair(source_language: str, target_language: str) -> None:
    argos_package, _ = _load_argos_modules()
    argos_package.update_package_index()
    available_packages = argos_package.get_available_packages()

    direct_package = _find_available_package(available_packages, source_language, target_language)
    if direct_package is not None:
        _download_and_install_package(direct_package)
        return

    for pivot_language in PIVOT_LANGUAGES:
        normalized_pivot = _normalize_code(pivot_language)
        if normalized_pivot in {_language_prefix(source_language), _language_prefix(target_language)}:
            continue
        source_to_pivot = _find_available_package(available_packages, source_language, normalized_pivot)
        pivot_to_target = _find_available_package(available_packages, normalized_pivot, target_language)
        if source_to_pivot is None or pivot_to_target is None:
            continue
        _download_and_install_package(source_to_pivot)
        _download_and_install_package(pivot_to_target)
        return

    raise RuntimeError(
        f"No Argos Translate package available for {source_language}->{target_language}"
    )


def ensure_language_pair_installed(source_language: str, target_language: str) -> None:
    normalized_source = _normalize_code(source_language) or DEFAULT_SOURCE_LANGUAGE
    normalized_target = _normalize_code(target_language) or DEFAULT_TARGET_LANGUAGE

    source = _find_installed_language(normalized_source)
    target = _find_installed_language(normalized_target)
    if source is None or target is None:
        _install_language_pair(normalized_source, normalized_target)

    source = _find_installed_language(normalized_source)
    target = _find_installed_language(normalized_target)
    if source is None or target is None:
        raise RuntimeError(
            f"Argos language pair unavailable for {normalized_source}->{normalized_target}"
        )


@lru_cache(maxsize=32)
def _get_translation_callable(source_language: str, target_language: str):
    normalized_source = _normalize_code(source_language)
    normalized_target = _normalize_code(target_language)

    source = _find_installed_language(normalized_source)
    target = _find_installed_language(normalized_target)
    if source is None or target is None:
        if not _should_auto_install_models():
            raise RuntimeError(
                f"Argos language package not installed for {normalized_source}->{normalized_target}. "
                "Run the install script or set TRANSLATION_RPC_AUTO_INSTALL=true."
            )
        _install_language_pair(normalized_source, normalized_target)
        source = _find_installed_language(normalized_source)
        target = _find_installed_language(normalized_target)

    if source is None or target is None:
        raise RuntimeError(
            f"Argos language pair unavailable for {normalized_source}->{normalized_target}"
        )

    translation = source.get_translation(target)
    if translation is not None:
        return translation.translate

    for pivot_language in PIVOT_LANGUAGES:
        pivot = _find_installed_language(pivot_language)
        if pivot is None:
            continue
        source_to_pivot = source.get_translation(pivot)
        pivot_to_target = pivot.get_translation(target)
        if source_to_pivot is None or pivot_to_target is None:
            continue

        def _pivot_translate(text: str, *, _first=source_to_pivot, _second=pivot_to_target) -> str:
            return _second.translate(_first.translate(text))

        return _pivot_translate

    if _should_auto_install_models():
        _install_language_pair(normalized_source, normalized_target)
        return _get_translation_callable.__wrapped__(normalized_source, normalized_target)

    raise RuntimeError(
        f"Argos translation object unavailable for {normalized_source}->{normalized_target}"
    )


def translate_blocks(
    blocks: list[dict[str, str]],
    *,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    source_language_hint: str | None = None,
    default_source_language: str = DEFAULT_SOURCE_LANGUAGE,
) -> list[dict[str, str]]:
    normalized_blocks = normalize_translation_blocks(blocks)
    if not normalized_blocks:
        return []

    normalized_target = _normalize_code(target_language) or DEFAULT_TARGET_LANGUAGE
    normalized_hint = _normalize_code(source_language_hint)
    results: list[dict[str, str]] = []

    for block in normalized_blocks:
        source_language = normalized_hint or detect_source_language(
            block["text"],
            default_source_language=default_source_language,
        )
        if _language_prefix(source_language) == _language_prefix(normalized_target):
            translation_text = block["text"]
        else:
            translator = _get_translation_callable(source_language, normalized_target)
            translation_text = str(translator(block["text"]) or "").strip() or block["text"]

        results.append(
            {
                "id": block["id"],
                "translation": translation_text,
                "source_language": source_language,
            }
        )

    return results
