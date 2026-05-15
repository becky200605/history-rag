"""Tests for SubagentToolLimitMiddleware."""

import asyncio

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.subagent_tool_limit_middleware import (
    TOOL_CALL_LIMIT,
    SubagentToolLimitMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content="You are a helpful subagent."),
    )


def _text_response() -> ModelResponse:
    """Plain text response — no tool calls."""
    return ModelResponse(result=[AIMessage(content="Here is my final answer.")])


def _tool_call_response() -> ModelResponse:
    """Response that still calls a tool (simulate non-compliant model)."""
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "kl-1",
                        "name": "knowledge_locate",
                        "args": {"book_id": "abc", "page": 1},
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )


def _make_tool_messages(count: int) -> list:
    """Return `count` ToolMessages to simulate an exhausted budget."""
    return [
        ToolMessage(content=f"result {i}", tool_call_id=f"tc-{i}", name="knowledge_locate")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Sync: wrap_model_call
# ---------------------------------------------------------------------------


class TestWrapModelCallBelowLimit:
    """When the tool-call count is still below the limit, the middleware is a no-op."""

    def test_passes_through_text_response(self):
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        call_count = []

        def handler(req: ModelRequest) -> ModelResponse:
            call_count.append(1)
            return _text_response()

        result = middleware.wrap_model_call(request, handler)

        assert len(call_count) == 1, "handler must be called exactly once below limit"
        assert result.result[0].content == "Here is my final answer."

    def test_passes_through_tool_call_response(self):
        """Even if the model still calls tools, we don't intervene below the limit."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        call_count = []

        def handler(req: ModelRequest) -> ModelResponse:
            call_count.append(1)
            return _tool_call_response()

        result = middleware.wrap_model_call(request, handler)

        assert len(call_count) == 1
        assert result.result[0].tool_calls  # original tool-call response passed through


class TestWrapModelCallAtLimit:
    """When tool_count >= TOOL_CALL_LIMIT the middleware must act."""

    def test_passes_through_when_response_has_no_tool_calls(self):
        """If the model already produced a plain answer, return it without retry."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        call_count = []

        def handler(req: ModelRequest) -> ModelResponse:
            call_count.append(1)
            return _text_response()

        result = middleware.wrap_model_call(request, handler)

        assert len(call_count) == 1, "no retry needed when model already gave a text answer"
        assert result.result[0].content == "Here is my final answer."

    def test_injects_wrap_up_and_retries_when_model_calls_tools(self):
        """On retry the middleware injects both the wrap-up and hard-stop messages."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        seen_requests: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen_requests.append(req)
            if len(seen_requests) == 1:
                return _tool_call_response()  # first call: model still calls tools
            return _text_response()           # retry: model complies

        result = middleware.wrap_model_call(request, handler)

        assert len(seen_requests) == 2
        retry_human_messages = [m for m in seen_requests[1].messages if isinstance(m, HumanMessage)]
        injected_contents = [str(m.content) for m in retry_human_messages]
        assert any("上限" in c for c in injected_contents), "wrap-up message not injected"
        assert any("再次提醒" in c for c in injected_contents), "hard-stop message not injected"
        assert result.result[0].content == "Here is my final answer."

    def test_wrap_up_message_includes_count_and_limit(self):
        """The wrap-up message must quote the current count and the configured limit."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        seen_requests: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen_requests.append(req)
            if len(seen_requests) == 1:
                return _tool_call_response()
            return _text_response()

        middleware.wrap_model_call(request, handler)

        retry_human_messages = [m for m in seen_requests[1].messages if isinstance(m, HumanMessage)]
        wrap_up_content = next(
            str(m.content) for m in retry_human_messages if "上限" in str(m.content)
        )
        assert str(TOOL_CALL_LIMIT) in wrap_up_content

    def test_returns_last_response_when_model_still_calls_tools_after_hard_stop(self):
        """If the model ignores both messages, return the last response (don't loop forever)."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        request = _build_request(messages)

        def handler(req: ModelRequest) -> ModelResponse:
            return _tool_call_response()  # always calls tools

        result = middleware.wrap_model_call(request, handler)

        # Must not raise; returns the last tool-calling response
        assert isinstance(result.result[0], AIMessage)
        assert result.result[0].tool_calls

    def test_triggers_at_exactly_tool_call_limit(self):
        """Boundary: exactly TOOL_CALL_LIMIT messages should trigger enforcement."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT)
        assert len(messages) == TOOL_CALL_LIMIT

        request = _build_request(messages)
        seen_requests: list[ModelRequest] = []

        def handler(req: ModelRequest) -> ModelResponse:
            seen_requests.append(req)
            if len(seen_requests) == 1:
                return _tool_call_response()
            return _text_response()

        middleware.wrap_model_call(request, handler)
        assert len(seen_requests) == 2, "enforcement must trigger at exactly TOOL_CALL_LIMIT"

    def test_does_not_trigger_one_below_limit(self):
        """Boundary: TOOL_CALL_LIMIT - 1 messages should NOT trigger enforcement."""
        middleware = SubagentToolLimitMiddleware()
        messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
        request = _build_request(messages)

        call_count = []

        def handler(req: ModelRequest) -> ModelResponse:
            call_count.append(1)
            return _tool_call_response()

        result = middleware.wrap_model_call(request, handler)
        assert len(call_count) == 1, "must call handler exactly once one below limit"
        assert result.result[0].tool_calls  # original tool-call response passed through


# ---------------------------------------------------------------------------
# Async: awrap_model_call
# ---------------------------------------------------------------------------


class TestAWrapModelCall:
    """Async version mirrors the sync version's logic."""

    def test_passes_through_when_below_limit(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT - 1)
            request = _build_request(messages)

            async def handler(req: ModelRequest) -> ModelResponse:
                return _tool_call_response()

            result = await middleware.awrap_model_call(request, handler)
            assert result.result[0].tool_calls

        asyncio.run(_run())

    def test_retries_when_at_limit_and_model_calls_tools(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT)
            request = _build_request(messages)
            seen: list[ModelRequest] = []

            async def handler(req: ModelRequest) -> ModelResponse:
                seen.append(req)
                if len(seen) == 1:
                    return _tool_call_response()
                return _text_response()

            result = await middleware.awrap_model_call(request, handler)

            assert len(seen) == 2
            retry_human = [m for m in seen[1].messages if isinstance(m, HumanMessage)]
            injected = [str(m.content) for m in retry_human]
            assert any("上限" in c for c in injected)
            assert result.result[0].content == "Here is my final answer."

        asyncio.run(_run())

    def test_returns_last_response_when_hard_stop_ignored(self):
        async def _run():
            middleware = SubagentToolLimitMiddleware()
            messages = _make_tool_messages(TOOL_CALL_LIMIT)
            request = _build_request(messages)

            async def handler(req: ModelRequest) -> ModelResponse:
                return _tool_call_response()

            result = await middleware.awrap_model_call(request, handler)
            assert result.result[0].tool_calls

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# _count_tool_calls
# ---------------------------------------------------------------------------


class TestCountToolCalls:
    def test_counts_only_tool_messages(self):
        middleware = SubagentToolLimitMiddleware()
        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="thinking"),
            ToolMessage(content="r1", tool_call_id="1", name="tool"),
            ToolMessage(content="r2", tool_call_id="2", name="tool"),
            AIMessage(content="ok"),
        ]
        assert middleware._count_tool_calls(messages) == 2

    def test_empty_messages(self):
        middleware = SubagentToolLimitMiddleware()
        assert middleware._count_tool_calls([]) == 0

    def test_no_tool_messages(self):
        middleware = SubagentToolLimitMiddleware()
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert middleware._count_tool_calls(messages) == 0
