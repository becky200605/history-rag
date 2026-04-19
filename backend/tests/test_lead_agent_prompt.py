import importlib.util
from pathlib import Path

_PROMPT_SPEC = importlib.util.spec_from_file_location(
    "test_lead_agent_prompt_module",
    Path(__file__).parent.parent / "src/agents/lead_agent/prompt.py",
)
prompt_module = importlib.util.module_from_spec(_PROMPT_SPEC)
assert _PROMPT_SPEC and _PROMPT_SPEC.loader
_PROMPT_SPEC.loader.exec_module(prompt_module)


def test_prompt_requires_joint_retrieval_and_historical_decomposition(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda: "")

    prompt = prompt_module.apply_prompt_template()

    assert "Book Search First Rule" in prompt
    assert "book_search(query=...)" in prompt
    assert "knowledge_folders" in prompt
    assert "Knowledge Folder Semantics Rule" in prompt
    assert "Scope Label Rule" in prompt
    assert "pass `knowledge_folders` copied from that tree into `book_search`" in prompt
    assert "<knowledge_directory_tree>" not in prompt
    assert "Book Group Label Rule" in prompt
    assert "Layered Book Routing Rule" in prompt
    assert "Batch-Within-Layer Rule" in prompt
    assert "Book List Coverage Rule" in prompt
    assert "Todo Book Tracking Rule" in prompt
    assert "Cross-Book Synthesis Rule" in prompt
    assert "Evidence Sufficiency Rule" in prompt
    assert "Decomposition Workflow Rule" in prompt
    assert "Planning-With-Prior-Knowledge Rule" in prompt
    assert "One-Facet-Per-Query Rule" in prompt
    assert "Historical Person Rule" in prompt
    assert "Historical Period Rule" in prompt
    assert "北洋政府" in prompt
    assert "Distributed Evidence Rule" in prompt
    assert "Historical Report Rule" in prompt
    assert "Recommended Report Shape" in prompt
    assert "Suggested Questions Rule" in prompt
    assert "建议问题" in prompt
    assert "Noise Filtering Rule" in prompt
    assert "Knowledge Checkpoint Rule" in prompt
    assert "knowledge_checkpoint` is mandatory" in prompt
    assert "Checkpoint Trigger Rule" in prompt
    assert "Checkpoint Cadence Rule" in prompt
    assert "High-Volume Context Rule" in prompt
    assert "Checkpoint Direction Rule" in prompt
    assert "Checkpoint Reading-Set Rule" in prompt
    assert "Checkpoint Next-Book Rule" in prompt
    assert "stop adding more raw retrieval and checkpoint first" in prompt
    assert "next investigation" in prompt
    assert "exact citation lines worth reusing" in prompt
    assert "knowledge_checkpoint" in prompt
    assert "Catalog Rescue Rule" in prompt
    assert "Query Formation Rule" in prompt
    assert "keyword pile-up" in prompt
    assert "vague" in prompt
    assert "Scope Is Hard Filter Rule" in prompt
    assert "Doc-ID Scope Alignment Rule" in prompt
    assert "Retry Discipline Rule" in prompt
    assert "Best-Match Book Rule" in prompt
    assert "Response Staging Rule" in prompt
    assert "回答正文" in prompt
    assert "Do not refuse after the first weak retrieval pass." in prompt
    assert "Return the answer directly in the conversation" in prompt
    assert "Direct Response Rule" in prompt
    assert "Table Citation Rule" in prompt
    assert "Data Coverage Rule" in prompt
    assert "Citation Offset Rule" in prompt
    assert "zero tolerated offset" in prompt
    assert "Strict Table/Data Citation Rule" in prompt
    assert "starts with `本表引文：`" in prompt
    assert "本表引文：" in prompt
    assert "All sources used for that table or data block must be listed there completely" in prompt
    assert "present_file" not in prompt
    assert "Final deliverables must be in `/mnt/user-data/outputs`" not in prompt
    assert "Final deliverables must be copied to `/mnt/user-data/outputs`" not in prompt
    assert "`核心通用书`" not in prompt
    assert "`专题支撑书`" not in prompt
    assert "`补充材料 / 参考工具书`" not in prompt
