"""Standalone translation RPC server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from concurrent import futures
from pathlib import Path

import grpc

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import translation_pb2
    import translation_pb2_grpc
    from translation_runtime import DEFAULT_TARGET_LANGUAGE, translate_blocks
else:
    from . import translation_pb2, translation_pb2_grpc
    from .translation_runtime import DEFAULT_TARGET_LANGUAGE, translate_blocks

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 50052
DEFAULT_WORKERS = 8
DEFAULT_MAX_GRPC_MESSAGE_BYTES = 32 * 1024 * 1024


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the standalone translation RPC server.")
    parser.add_argument("--host", default=os.getenv("TRANSLATION_RPC_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TRANSLATION_RPC_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("TRANSLATION_RPC_WORKERS", str(DEFAULT_WORKERS))),
    )
    parser.add_argument(
        "--api-token",
        default=os.getenv("TRANSLATION_RPC_API_TOKEN") or "",
        help="Optional bearer token required by clients.",
    )
    parser.add_argument(
        "--auto-install",
        action="store_true",
        default=(os.getenv("TRANSLATION_RPC_AUTO_INSTALL") or "").strip().lower()
        in {"1", "true", "yes", "on"},
        help="Automatically install missing Argos language packages on demand.",
    )
    return parser.parse_args()


def _get_max_grpc_message_bytes() -> int:
    raw_value = (os.getenv("TRANSLATION_GRPC_MAX_MESSAGE_BYTES") or "").strip()
    if not raw_value:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    return parsed if parsed > 0 else DEFAULT_MAX_GRPC_MESSAGE_BYTES


def _extract_bearer_token(context: grpc.ServicerContext) -> str | None:
    for key, value in context.invocation_metadata():
        if key.lower() != "authorization":
            continue
        prefix = "bearer "
        if value.lower().startswith(prefix):
            return value[len(prefix) :].strip()
    return None


class TranslationService(translation_pb2_grpc.TranslationServiceServicer):
    def __init__(self, *, api_token: str | None = None):
        self.api_token = (api_token or "").strip() or None

    def TranslateBlocks(self, request, context):
        if self.api_token:
            token = _extract_bearer_token(context)
            if token != self.api_token:
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid translation API token")

        blocks = [
            {"id": block.key.strip(), "text": block.text.strip()}
            for block in request.blocks
            if block.key.strip() and block.text.strip()
        ]
        if not blocks:
            return translation_pb2.TranslateBlocksResponse(task_id=str(uuid.uuid4()))

        try:
            translations = translate_blocks(
                blocks,
                target_language=request.target_language or DEFAULT_TARGET_LANGUAGE,
                source_language_hint=request.source_language_hint or None,
            )
        except Exception as exc:
            logging.exception("Translation RPC request failed")
            context.abort(grpc.StatusCode.INTERNAL, str(exc))

        detected_languages = {
            item.get("source_language", "").strip()
            for item in translations
            if str(item.get("source_language") or "").strip()
        }
        detected_source_language = detected_languages.pop() if len(detected_languages) == 1 else ""

        return translation_pb2.TranslateBlocksResponse(
            task_id=str(uuid.uuid4()),
            translations=[
                translation_pb2.TranslationResult(
                    key=item["id"],
                    translation=item["translation"],
                    source_language=item.get("source_language", ""),
                )
                for item in translations
            ],
            detected_source_language=detected_source_language,
        )


def serve(*, host: str, port: int, workers: int, api_token: str | None = None) -> None:
    max_message_bytes = _get_max_grpc_message_bytes()
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max(1, workers)),
        options=[
            ("grpc.max_send_message_length", max_message_bytes),
            ("grpc.max_receive_message_length", max_message_bytes),
        ],
    )
    translation_pb2_grpc.add_TranslationServiceServicer_to_server(
        TranslationService(api_token=api_token),
        server,
    )
    bind_target = f"{host}:{port}"
    server.add_insecure_port(bind_target)
    server.start()
    logging.info("Translation RPC server listening on %s", bind_target)
    server.wait_for_termination()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    if args.auto_install:
        os.environ["TRANSLATION_RPC_AUTO_INSTALL"] = "true"
    serve(host=args.host, port=args.port, workers=args.workers, api_token=args.api_token)


if __name__ == "__main__":
    main()
