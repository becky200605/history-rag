"""Compress old knowledge tool outputs after a retrieval checkpoint is created."""

from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

GROUNDING_TOOL_NAMES = {"knowledge_search", "knowledge_locate"}
CHECKPOINT_TOOL_NAME = "knowledge_checkpoint"


class KnowledgeCheckpointMiddleware(AgentMiddleware[AgentState]):
    """Hide raw grounding tool payloads once a later checkpoint summarizes them."""

    def _build_patched_messages(self, messages: list) -> list | None:
        last_checkpoint_index = None
        for index, message in enumerate(messages):
            if isinstance(message, ToolMessage) and getattr(message, "name", None) == CHECKPOINT_TOOL_NAME:
                last_checkpoint_index = index

        if last_checkpoint_index is None:
            return None

        patched: list = []
        changed = False
        for index, message in enumerate(messages):
            if (
                index < last_checkpoint_index
                and isinstance(message, ToolMessage)
                and getattr(message, "name", None) in GROUNDING_TOOL_NAMES
            ):
                placeholder = f"【已调用{message.name}工具】该原始检索结果已由后续 knowledge_checkpoint 检查点压缩。"
                if str(message.content) != placeholder:
                    changed = True
                    patched.append(message.model_copy(update={"content": placeholder}))
                    continue
            patched.append(message)

        return patched if changed else None

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
