"""Middleware for automatic thread title generation."""

import re
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the thread after the first user message."""

    state_schema = TitleMiddlewareState

    _FINAL_TITLE_PATTERNS = (
        re.compile(r"^\s*(?:final\s+answer|title)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE),
        re.compile(r"^\s*(?:最终标题|标题)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE),
    )
    _REASONING_LINE_PATTERNS = (
        re.compile(r"^\s*thinking\s+process\b", re.IGNORECASE),
        re.compile(r"^\s*analy[sz]e\b", re.IGNORECASE),
        re.compile(r"^\s*(?:input|task|constraints?)\s*[:：]", re.IGNORECASE),
        re.compile(r"^\s*(?:drafting|selection)\b", re.IGNORECASE),
        re.compile(r"^\s*(?:let'?s|i will|i need to)\b", re.IGNORECASE),
    )

    def _split_lines(self, text: str) -> list[str]:
        return [line.strip().strip('"').strip("'") for line in text.splitlines() if line.strip()]

    def _looks_like_reasoning_line(self, line: str) -> bool:
        if len(line) > 80:
            return True
        if line.startswith(("-", "*")):
            return True
        return any(pattern.match(line) for pattern in self._REASONING_LINE_PATTERNS)

    def _looks_like_title(self, line: str, *, max_chars: int, max_words: int) -> bool:
        if not line:
            return False
        if len(line) > max_chars:
            return False
        if len(line.split()) > max_words:
            return False
        if self._looks_like_reasoning_line(line):
            return False
        return True

    def _extract_title_from_response(self, text: str, *, max_chars: int, max_words: int) -> str:
        raw = text.strip().strip('"').strip("'")
        if not raw:
            return ""

        for pattern in self._FINAL_TITLE_PATTERNS:
            for line in self._split_lines(raw):
                match = pattern.match(line)
                if match:
                    candidate = match.group(1).strip().strip('"').strip("'")
                    if self._looks_like_title(candidate, max_chars=max_chars, max_words=max_words):
                        return candidate[:max_chars]

        lines = self._split_lines(raw)
        plausible = [
            line for line in lines if self._looks_like_title(line, max_chars=max_chars, max_words=max_words)
        ]
        if plausible:
            return min(plausible, key=len)[:max_chars]

        return raw[:max_chars]

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """Check if we should generate a title for this thread."""
        config = get_title_config()
        if not config.enabled:
            return False

        # Check if thread already has a title in state
        if state.get("title"):
            return False

        # Check if this is the first turn (has at least one user message and one assistant response)
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        # Count user and assistant messages
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        # Generate title after first complete exchange
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    def _generate_title(self, state: TitleMiddlewareState) -> str:
        """Generate a concise title based on the conversation."""
        config = get_title_config()
        messages = state.get("messages", [])

        # Get first user message and first assistant response
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        # Ensure content is string (LangChain messages can have list content)
        user_msg = str(user_msg_content) if user_msg_content else ""
        assistant_msg = str(assistant_msg_content) if assistant_msg_content else ""

        # Use a lightweight model to generate title
        model = create_chat_model(name=config.model_name, thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = model.invoke(prompt)
            # Ensure response content is string
            title_content = str(response.content) if response.content else ""
            title = self._extract_title_from_response(
                title_content,
                max_chars=config.max_chars,
                max_words=config.max_words,
            )
            # Limit to max characters
            return title[: config.max_chars] if len(title) > config.max_chars else title
        except Exception as e:
            print(f"Failed to generate title: {e}")
            # Fallback: use first part of user message (by character count)
            fallback_chars = min(config.max_chars, 50)  # Use max_chars or 50, whichever is smaller
            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "..."
            return user_msg if user_msg else "New Conversation"

    @override
    def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Generate and set thread title after the first agent response."""
        if self._should_generate_title(state):
            title = self._generate_title(state)
            print(f"Generated thread title: {title}")

            # Store title in state (will be persisted by checkpointer if configured)
            return {"title": title}

        return None
