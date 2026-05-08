"""Middleware to ensure knowledge_citation_registry is explicitly written back to LangGraph state.

Tools currently mutate state["knowledge_citation_registry"] in-place via
register_citation_marker(). This works by accident in single-threaded execution
because LastValue channels return direct object references, but it is NOT
reliable across LangGraph supersteps, subgraph calls, or checkpointing.

This middleware syncs the registry back into the state channel after every
model turn so that LangGraph's apply_writes() can persist it properly.
"""

from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY


class CitationRegistrySyncMiddleware(AgentMiddleware[ThreadState]):
    """Sync citation registry from runtime.state back to the LangGraph channel."""

    @override
    def after_model(self, state: ThreadState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        raw_registry = state.get(KNOWLEDGE_CITATION_REGISTRY_KEY)
        if isinstance(raw_registry, list) and raw_registry:
            # Return a shallow copy so LangGraph sees a "new" value and triggers channel update.
            return {KNOWLEDGE_CITATION_REGISTRY_KEY: list(raw_registry)}
        return None

    @override
    def aafter_model(self, state: ThreadState, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        return self.after_model(state, runtime)
