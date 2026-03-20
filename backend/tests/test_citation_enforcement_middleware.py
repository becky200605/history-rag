"""Tests for citation enforcement middleware."""

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.citation_enforcement_middleware import (
    FINAL_FALLBACK_RESPONSE,
    CitationEnforcementMiddleware,
)


def _build_request() -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content="citation: [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)",
                tool_call_id="tool-call-1",
                name="knowledge_search",
            ),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _bad_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="这是一个没有 citation 的回答。")])


def _good_response() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content=(
                    "根据现有资料，可以得出相关结论。"
                    "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)\n\n"
                    "参考文献\n"
                    "1. [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                )
            )
        ]
    )


class TestCitationEnforcementMiddleware:
    """Tests for retry and fallback behavior."""

    def test_retries_until_second_retry_succeeds(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request()
        responses = [_bad_response(), _bad_response(), _good_response()]
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return responses[len(seen_requests) - 1]

        final_response = middleware.wrap_model_call(request, handler)

        assert final_response.result[-1].content == _good_response().result[-1].content
        assert len(seen_requests) == 3
        assert seen_requests[1].system_message is not None
        assert "previous draft was blocked" in str(seen_requests[1].system_message.content)
        assert seen_requests[2].system_message is not None
        assert "reuse the exact `citation:` lines returned by `knowledge_search`" in str(
            seen_requests[2].system_message.content
        ).lower()

    def test_returns_final_refusal_after_all_retries_fail(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request()
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _bad_response()

        final_response = middleware.wrap_model_call(request, handler)

        assert len(seen_requests) == 3
        assert final_response.result[-1].content == FINAL_FALLBACK_RESPONSE
        assert final_response.result[-1].tool_calls == []
