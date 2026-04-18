"""Tests for citation enforcement middleware."""

from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.citation_enforcement_middleware import (
    FINAL_FALLBACK_RESPONSE,
    CitationEnforcementMiddleware,
)


class _SuggestionModel:
    def __init__(self, suggestions: str | None = None) -> None:
        self.suggestions = suggestions or "问题一？\n问题二？\n问题三？"

    def invoke(self, messages):
        return SimpleNamespace(content=self.suggestions)

    async def ainvoke(self, messages):
        return SimpleNamespace(content=self.suggestions)


def _build_request(model=None, tool_name: str = "knowledge_search") -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content="citation: [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)",
                tool_call_id="tool-call-1",
                name=tool_name,
            ),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _build_request_with_variant_citation(model=None) -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content=(
                    "citation: "
                    "[citation:光绪朝上谕档第一七册（光绪一七年） 原书第263页第6段]"
                    "(/api/knowledge/docs/book.pdf?page_no=263&paragraph_no=6)"
                ),
                tool_call_id="tool-call-1",
                name="knowledge_locate",
            ),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _build_request_with_checkpoint_citation(model=None) -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content="【已调用knowledge_search工具】该原始检索结果已由后续 knowledge_checkpoint 检查点压缩。",
                tool_call_id="tool-call-0",
                name="knowledge_search",
            ),
            ToolMessage(
                content=(
                    "# 检索检查点：光绪朝东华录\n"
                    "## 关键引文\n"
                    "- [citation:光绪朝东华录 原书第2567页第1段]"
                    "(/api/knowledge/docs/dhl.pdf?page_no=2567&paragraph_no=1)"
                ),
                tool_call_id="tool-call-1",
                name="knowledge_checkpoint",
            ),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _bad_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="这是一个没有 citation 的回答。")])


def _good_stage_one_response() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content=(
                    "根据现有资料，可以得出相关结论。"
                    "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                )
            )
        ]
    )


def _good_stage_one_response_with_bare_citation() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="根据现有资料，可以得出相关结论。[citation:史料 第7页第2段]")])


def _response_with_prebuilt_sections() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content=(
                    "根据现有资料，可以得出相关结论。"
                    "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)\n\n"
                    "参考文献\n"
                    "1. [citation:旧引用](/old)\n\n"
                    "建议问题\n"
                    "1. 旧问题？"
                )
            )
        ]
    )


def _refusal_response(content: str) -> ModelResponse:
    return ModelResponse(result=[AIMessage(content=content)])


class TestCitationEnforcementMiddleware:
    """Tests for retry, staged assembly, and refusal behavior."""

    def test_retries_until_second_retry_succeeds(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("继续追问一？\n继续追问二？\n继续追问三？"))
        responses = [_bad_response(), _bad_response(), _good_stage_one_response()]
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return responses[len(seen_requests) - 1]

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "根据现有资料，可以得出相关结论。" in content
        assert "参考文献" in content
        assert "1. [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in content
        assert "建议问题" in content
        assert "1. 继续追问一？" in content
        assert len(seen_requests) == 3
        assert seen_requests[1].system_message is not None
        assert "previous draft was blocked" in str(seen_requests[1].system_message.content)
        assert "Available citation lines from this turn" in str(seen_requests[1].system_message.content)
        assert "citation: [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in str(
            seen_requests[1].system_message.content
        )
        assert seen_requests[2].system_message is not None
        assert "reuse the exact `citation:` lines returned by `knowledge_search`" in str(
            seen_requests[2].system_message.content
        ).lower()

    def test_enforces_citations_for_knowledge_locate_too(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(
            model=_SuggestionModel("继续缩到段落？\n继续核对上下文？\n继续追问史料差异？"),
            tool_name="knowledge_locate",
        )
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _bad_response() if len(seen_requests) < 3 else _good_stage_one_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 3
        assert "[citation:史料 第7页第2段]" in content
        assert "knowledge_locate" in str(seen_requests[1].system_message.content)

    def test_accepts_bare_citation_and_upgrades_it_from_grounding_messages(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("继续追问一？\n继续追问二？\n继续追问三？"))

        def handler(_: ModelRequest) -> ModelResponse:
            return _good_stage_one_response_with_bare_citation()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in content
        assert "参考文献" in content

    def test_upgrades_variant_spacing_bare_citation_with_structured_matching(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_variant_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可据档案得出结论。"
                            "[citation:光绪朝上谕档第一七册（光绪一七年）原书第 263 页第 6 段]"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert (
            "[citation:光绪朝上谕档第一七册（光绪一七年） 原书第263页第6段]"
            "(/api/knowledge/docs/book.pdf?page_no=263&paragraph_no=6)"
        ) in content

    def test_upgrades_bare_citation_from_checkpoint_candidates(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_checkpoint_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可据东华录得出结论。"
                            "[citation:光绪朝东华录 原书第 2567 页第 1 段]"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert (
            "[citation:光绪朝东华录 原书第2567页第1段]"
            "(/api/knowledge/docs/dhl.pdf?page_no=2567&paragraph_no=1)"
        ) in content

    def test_returns_final_refusal_after_all_retries_fail_and_skips_reference_stage(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("缩小范围？\n指定书名？\n补充线索？"))
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _bad_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 3
        assert content.startswith(FINAL_FALLBACK_RESPONSE)
        assert "参考文献" not in content
        assert "建议问题" in content
        assert "1. 缩小范围？" in content
        assert final_response.result[-1].tool_calls == []

    def test_stage_two_rebuilds_reference_section_and_stage_three_rebuilds_suggestions(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("新问题一？\n新问题二？\n新问题三？"))
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _response_with_prebuilt_sections()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 1
        assert "[citation:旧引用](/old)" not in content
        assert "旧问题？" not in content
        assert "参考文献" in content
        assert "1. [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in content
        assert "建议问题" in content
        assert "1. 新问题一？" in content

    def test_allows_refusal_without_reference_section_when_catalog_has_no_material(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("缩小到更具体时期？\n指定书名或章节？\n优先核实哪条史料？"))
        seen_requests: list[ModelRequest] = []
        refusal = _refusal_response("【无法回答】当前书目中暂无相关资料，无法根据现有资料回答这个问题。")

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return refusal

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 1
        assert content.startswith("【无法回答】当前书目中暂无相关资料")
        assert "参考文献" not in content
        assert "建议问题" in content

    def test_allows_no_relevant_information_refusal_without_reference_section(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("换一个更窄的问题？\n指定材料范围？\n先查哪条线索？"))
        seen_requests: list[ModelRequest] = []
        refusal = _refusal_response("【无法回答】No relevant information found in the knowledge base, so I cannot answer from the provided materials.")

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return refusal

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 1
        assert content.startswith("【无法回答】No relevant information found")
        assert "参考文献" not in content
        assert "建议问题" in content
