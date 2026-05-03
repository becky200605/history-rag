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
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.suggestions)

    async def ainvoke(self, messages):
        self.messages = messages
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


def _build_request_with_parenthesized_url_citation(model=None) -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content=(
                    "citation: "
                    "[citation:民国财政史 (杨荫溥) 原书第10页第1段]"
                    "(</api/knowledge/docs/%E6%B0%91%E5%9B%BD%E8%B4%A2%E6%94%BF%E5%8F%B2%20%28%E6%9D%A8%E8%8D%AB%E6%BA%A5%29.pdf?page_no=10&paragraph_no=1>)"
                ),
                tool_call_id="tool-call-1",
                name="knowledge_locate",
            ),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _build_request_with_long_encoded_citation(model=None) -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content=(
                    "citation: "
                    "[citation:张之洞全集 12 书札 家书 勤学篇 輶轩语 书目答问 读经札记 论金石札路上 古文 骈体文 诗集 弟子记_12733686_可搜索 原书第178页第1段]"
                    "(</api/knowledge/docs/%E5%BC%A0%E4%B9%8B%E6%B4%9E%E5%85%A8%E9%9B%86%2012%20%E4%B9%A6%E6%9C%AD%20%E5%AE%B6%E4%B9%A6%20%E5%8B%A4%E5%AD%A6%E7%AF%87%20%E8%BC%B6%E8%BD%A9%E8%AF%AD%20%E4%B9%A6%E7%9B%AE%E7%AD%94%E9%97%AE%20%E8%AF%BB%E7%BB%8F%E6%9C%AD%E8%AE%B0%20%E8%AE%BA%E9%87%91%E7%9F%B3%E6%9C%AD%E8%B7%AF%E4%B8%8A%2B%E5%8F%A4%E6%96%87%20%E9%AA%88%E4%BD%93%E6%96%87%20%E8%AF%97%E9%9B%86%20%E5%BC%9F%E5%AD%90%E8%AE%B0_12733686_%E5%8F%AF%E6%90%9C%E7%B4%A2.pdf?page_no=178&pdf_page_no=178&paragraph_no=1&citation_source_kind=structured#page=178>)"
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


def _build_request_with_standard_citation(model=None) -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content="请根据知识库回答这个问题"),
            ToolMessage(
                content=(
                    "citation: "
                    "[citation:史料 第7页第2段]"
                    "(/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                ),
                tool_call_id="tool-call-1",
                name="knowledge_locate",
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

    def test_accepts_angle_bracket_citation_url_with_parentheses_in_title_or_path(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_parenthesized_url_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可以据此得出结论。"
                            "[citation:民国财政史 (杨荫溥) 原书第10页第1段]"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert (
            "[citation:民国财政史 (杨荫溥) 原书第10页第1段]"
            "(</api/knowledge/docs/%E6%B0%91%E5%9B%BD%E8%B4%A2%E6%94%BF%E5%8F%B2%20%28%E6%9D%A8%E8%8D%AB%E6%BA%A5%29.pdf?page_no=10&paragraph_no=1>)"
        ) in content

    def test_repairs_truncated_citation_link_using_tool_candidate(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_parenthesized_url_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可以据此得出结论。"
                            "[citation:民国财政史 (杨荫溥) 原书第10页第1段]"
                            "(/api/knowledge/docs/民国财政史%20(杨荫溥)"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert (
            "[citation:民国财政史 (杨荫溥) 原书第10页第1段]"
            "(</api/knowledge/docs/%E6%B0%91%E5%9B%BD%E8%B4%A2%E6%94%BF%E5%8F%B2%20%28%E6%9D%A8%E8%8D%AB%E6%BA%A5%29.pdf?page_no=10&paragraph_no=1>)"
        ) in content

    def test_repairs_citation_link_with_raw_spaces_using_tool_candidate(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_long_encoded_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可以据此得出结论。"
                            "[citation:张之洞全集 12 书札 家书 勤学篇 輶轩语 书目答问 读经札记 论金石札路上 古文 骈体文 诗集 弟子记_12733686_可搜索 原书第178页第1段]"
                            "(/api/knowledge/docs/张之洞全集 12 书札 家书 勤学篇 輶轩语 书目答问 "
                            "读经札记 论金石札路上+古文 骈体文 诗集 弟子记_12733686_可搜索.pdf"
                            "?page_no=178&pdf_page_no=178&paragraph_no=1&citation_source_kind=structured#page=178)"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert (
            "[citation:张之洞全集 12 书札 家书 勤学篇 輶轩语 书目答问 读经札记 论金石札路上 古文 骈体文 诗集 弟子记_12733686_可搜索 原书第178页第1段]"
            "(</api/knowledge/docs/%E5%BC%A0%E4%B9%8B%E6%B4%9E%E5%85%A8%E9%9B%86%2012%20%E4%B9%A6%E6%9C%AD%20%E5%AE%B6%E4%B9%A6%20%E5%8B%A4%E5%AD%A6%E7%AF%87%20%E8%BC%B6%E8%BD%A9%E8%AF%AD%20%E4%B9%A6%E7%9B%AE%E7%AD%94%E9%97%AE%20%E8%AF%BB%E7%BB%8F%E6%9C%AD%E8%AE%B0%20%E8%AE%BA%E9%87%91%E7%9F%B3%E6%9C%AD%E8%B7%AF%E4%B8%8A%2B%E5%8F%A4%E6%96%87%20%E9%AA%88%E4%BD%93%E6%96%87%20%E8%AF%97%E9%9B%86%20%E5%BC%9F%E5%AD%90%E8%AE%B0_12733686_%E5%8F%AF%E6%90%9C%E7%B4%A2.pdf?page_no=178&pdf_page_no=178&paragraph_no=1&citation_source_kind=structured#page=178>)"
        ) in content
        assert "(/api/knowledge/docs/张之洞全集 12 书札" not in content

    def test_normalizes_internal_citation_with_raw_spaces_in_body_and_references(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_standard_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可据现有资料得出一个可靠结论。"
                            "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                            "另有一条损坏引用"
                            "[citation:中国财政通史 第7卷 清代财政史 下 原书第514页]"
                            "(/api/knowledge/docs/中国财政通史 第7卷 清代财政史 下.pdf?page_no=514)"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in content
        assert (
            "[citation:中国财政通史 第7卷 清代财政史 下 原书第514页]"
            "(/api/knowledge/docs/%E4%B8%AD%E5%9B%BD%E8%B4%A2%E6%94%BF%E9%80%9A%E5%8F%B2%20%E7%AC%AC7%E5%8D%B7%20%E6%B8%85%E4%BB%A3%E8%B4%A2%E6%94%BF%E5%8F%B2%20%E4%B8%8B.pdf?page_no=514)"
        ) in content
        assert "/api/knowledge/docs/中国财政通史 第7卷 清代财政史 下.pdf?page_no=514" not in content

    def test_drops_unparseable_citation_with_invalid_scheme_from_body_and_references(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request_with_standard_citation()

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "可据现有资料得出一个可靠结论。"
                            "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                            "另有一条损坏引用"
                            "[citation:中国财政通史 第7卷 清代财政史 下 原书第676页]"
                            "(citations:中国财政通史 第7卷 清代财政史 下 原书第677页)"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)" in content
        assert "(citations:中国财政通史 第7卷 清代财政史 下 原书第677页)" not in content
        assert "中国财政通史 第7卷 清代财政史 下 原书第676页" not in content.split("参考文献", 1)[-1]

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

    def test_stage_three_drops_leaked_minimax_thinking_from_suggestions(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(
            model=_SuggestionModel(
                "{'thinking': '先分析应该问什么。', 'type': 'thinking', 'index': 0, 'signature': 'abc'}\n"
                "你能帮我分析或研究哪方面的内容？\n"
                "我注意到知识库中有一份刘恺卿(1905-1952)的人物档案，需要我帮你深入了解吗？"
            )
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return _good_stage_one_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "1. 你能帮我分析或研究哪方面的内容？" in content
        assert "2. 我注意到知识库中有一份刘恺卿(1905-1952)的人物档案，需要我帮你深入了解吗？" in content
        assert "3. 围绕" in content
        assert "thinking" not in content
        assert "\n1. \n" not in content

    def test_stage_three_ignores_task_memory_injection_when_building_suggestions(self):
        middleware = CitationEnforcementMiddleware()
        injected = (
            "<task_memory_matches>\n"
            "系统插入提示（不是用户的新问题）：以下是基于当前任务标题与 query 匹配到的历史主任务/子任务结果。\n"
            "当前 query：张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？\n"
            "</task_memory_matches>"
        )
        request = ModelRequest(
            model=_SuggestionModel(
                "围绕“系统插入提示（不是用户的新问题）”，下一步最值得继续展开的关键阶段或专题是什么？\n"
                "如果继续深挖“<task_memory_matches> 系统插入提示”，最需要补充证据的机制是哪一项？\n"
                "张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"
            ),
            messages=[
                HumanMessage(content=injected),
                HumanMessage(content="张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"),
                ToolMessage(
                    content="citation: [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)",
                    tool_call_id="tool-call-1",
                    name="knowledge_search",
                ),
            ],
            system_message=SystemMessage(content="You are a helpful assistant."),
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return _good_stage_one_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "系统插入提示" not in content
        assert "<task_memory_matches>" not in content
        assert "张之洞创办汉阳铁厂" in content

    def test_stage_three_feeds_current_findings_context_to_suggestion_model(self):
        middleware = CitationEnforcementMiddleware()
        suggestion_model = _SuggestionModel(
            "盛宣怀在轮船招商局的官督商办机制如何影响晚清财政与商股关系？\n"
            "电报、铁路与银行事业之间的筹资网络是否构成盛宣怀贡献的制度核心？\n"
            "甲午后铁路国有化争议如何改变对盛宣怀实业贡献的历史评价？"
        )
        request = ModelRequest(
            model=suggestion_model,
            messages=[
                HumanMessage(content="盛宣怀是谁，有什么突出贡献"),
                ToolMessage(
                    content=(
                        "### Todo: 查盛宣怀的晚清实业财政活动\n"
                        "任务结果:\n"
                        "盛宣怀的突出贡献集中在轮船招商局、电报、铁路、银行等官督商办事业，"
                        "但仍需补查这些事业如何连接财政筹款、商股募集与国家利权。"
                    ),
                    tool_call_id="todo-call-1",
                    name="write_todos",
                ),
                ToolMessage(
                    content=(
                        "citation: "
                        "[citation:史料 第7页第2段]"
                        "(/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                    ),
                    tool_call_id="tool-call-1",
                    name="knowledge_locate",
                ),
            ],
            system_message=SystemMessage(content="You are a helpful assistant."),
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "盛宣怀是晚清官僚型实业人物，其贡献主要体现为推动轮船招商局、电报、铁路、银行等新式事业。"
                            "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        prompt = str(suggestion_model.messages[1].content)
        content = str(final_response.result[-1].content)

        assert "当前主任务/子任务已有发现摘要" in prompt
        assert "轮船招商局" in prompt
        assert "官督商办" in prompt
        assert "商股募集" in prompt
        assert "关键阶段或专题是什么" not in content
        assert "盛宣怀在轮船招商局的官督商办机制" in content

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
