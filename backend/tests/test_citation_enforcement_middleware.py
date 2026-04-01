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


def _good_response_without_reference_section() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content="根据现有资料，可以得出相关结论。[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
            )
        ]
    )


def _refusal_response(content: str) -> ModelResponse:
    return ModelResponse(result=[AIMessage(content=content)])


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

    def test_retries_when_only_citation_exists_without_reference_section(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request()
        seen_requests: list[ModelRequest] = []
        responses = [_good_response_without_reference_section(), _good_response()]

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return responses[len(seen_requests) - 1]

        final_response = middleware.wrap_model_call(request, handler)

        assert len(seen_requests) == 2
        assert final_response.result[-1].content == _good_response().result[-1].content

    def test_allows_refusal_without_reference_section_when_catalog_has_no_material(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request()
        seen_requests: list[ModelRequest] = []
        refusal = _refusal_response("【无法回答】当前书目中暂无相关资料，无法根据现有资料回答这个问题。")

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return refusal

        final_response = middleware.wrap_model_call(request, handler)

        assert len(seen_requests) == 1
        assert final_response.result[-1].content == refusal.result[-1].content

    def test_allows_no_relevant_information_refusal_without_reference_section(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request()
        seen_requests: list[ModelRequest] = []
        refusal = _refusal_response("【无法回答】No relevant information found in the knowledge base, so I cannot answer from the provided materials.")

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return refusal

        final_response = middleware.wrap_model_call(request, handler)

        assert len(seen_requests) == 1
        assert final_response.result[-1].content == refusal.result[-1].content
