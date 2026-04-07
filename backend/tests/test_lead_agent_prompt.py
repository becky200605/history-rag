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
    assert "Layered Book Routing Rule" in prompt
    assert "Book Coverage Rule" in prompt
    assert "Cross-Book Synthesis Rule" in prompt
    assert "Scattered Evidence Rule" in prompt
    assert "Pre-Answer Sufficiency Check" in prompt
    assert "Historical Person Rule" in prompt
    assert "Historical Period Rule" in prompt
    assert "北洋政府" in prompt
    assert "Distributed Evidence Rule" in prompt
    assert "Historical Report Rule" in prompt
    assert "Recommended Report Shape" in prompt
    assert "Suggested Questions Rule" in prompt
    assert "建议问题" in prompt
    assert "Noise Filtering Rule" in prompt
    assert "Catalog Rescue Rule" in prompt
