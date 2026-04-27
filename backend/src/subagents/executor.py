"""Subagent execution engine."""

import logging
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.runnables import RunnableConfig

from src.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from src.models import create_chat_model
from src.subagents.config import SubagentConfig
from src.utils.error_logging import append_error_doc
from src.utils.subtask_logging import log_subtask_event

logger = logging.getLogger(__name__)


class SubagentStatus(Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Unique identifier for this execution.
        trace_id: Trace ID for distributed tracing (links parent and subagent logs).
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed).
        started_at: When execution started.
        completed_at: When execution completed.
        ai_messages: List of complete AI messages (as dicts) generated during execution.
        structured_result: Parsed structured sections extracted from the final result.
    """

    task_id: str
    trace_id: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    structured_result: dict[str, Any] | None = None

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []


_SECTION_ALIASES: dict[str, str] = {
    "摘要": "summary",
    "总结": "summary",
    "summary": "summary",
    "关键发现": "findings",
    "发现": "findings",
    "findings": "findings",
    "关键引文": "citations",
    "引文": "citations",
    "引用": "citations",
    "citations": "citations",
    "未解决缺口": "open_questions",
    "缺口": "open_questions",
    "待继续检索": "open_questions",
    "open questions": "open_questions",
    "gaps": "open_questions",
}

_REFUSAL_PREFIXES = (
    "【证据不足】",
    "【无法确认】",
    "【无法回答】",
    "【信息不足】",
)


def _normalize_heading(heading: str) -> str:
    return re.sub(r"[\s:：\-]+", "", heading.strip().lower())


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = " ".join(item.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item.strip())
    return deduped


def _extract_bullets(block: str) -> list[str]:
    bullets: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[-*•]\s+", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line).strip())
            continue
        if re.match(r"^\d+\.\s+", line):
            bullets.append(re.sub(r"^\d+\.\s+", "", line).strip())
    return _dedupe_strings([item for item in bullets if item and item != "无"])


def _extract_citations(text: str) -> list[str]:
    citations = re.findall(r"\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]+)\)", text)
    return _dedupe_strings(citations)


def _strip_reasoning_from_message_dict(message_dict: dict[str, Any]) -> dict[str, Any]:
    additional_kwargs = message_dict.get("additional_kwargs")
    if isinstance(additional_kwargs, dict):
        additional_kwargs.pop("reasoning_content", None)
        additional_kwargs.pop("reasoning", None)
    return message_dict


def _parse_refusal_summary(summary: str) -> tuple[bool, str | None]:
    normalized = summary.strip()
    for prefix in _REFUSAL_PREFIXES:
        if normalized.startswith(prefix):
            reason = normalized[len(prefix):].strip(" ：:;；，,")
            return True, reason or None
    return False, None


def _parse_structured_subtask_result(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in stripped.splitlines():
        heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading_match:
            normalized_heading = _normalize_heading(heading_match.group(1))
            current_key = _SECTION_ALIASES.get(normalized_heading)
            if current_key is not None:
                sections.setdefault(current_key, [])
            else:
                current_key = None
            continue

        if current_key is not None:
            sections.setdefault(current_key, []).append(line)

    summary_block = "\n".join(sections.get("summary", [])).strip()
    findings_block = "\n".join(sections.get("findings", [])).strip()
    citations_block = "\n".join(sections.get("citations", [])).strip()
    gaps_block = "\n".join(sections.get("open_questions", [])).strip()

    summary = summary_block
    if not summary:
        first_paragraph = stripped.split("\n\n", 1)[0].strip()
        summary = first_paragraph if first_paragraph else ""

    findings = _extract_bullets(findings_block)
    citations = _extract_bullets(citations_block) or _extract_citations(citations_block) or _extract_citations(stripped)
    open_questions = _extract_bullets(gaps_block)

    parsed = {
        "summary": summary,
        "findings": findings,
        "citations": citations,
        "open_questions": open_questions,
    }

    is_refusal, refusal_reason = _parse_refusal_summary(summary)
    if is_refusal:
        parsed["is_refusal"] = True
        if refusal_reason:
            parsed["refusal_reason"] = refusal_reason

    if not any(
        [
            parsed["summary"],
            parsed["findings"],
            parsed["citations"],
            parsed["open_questions"],
        ]
    ):
        return None

    return parsed


# Global storage for background task results
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# Default subagent concurrency budget for orchestrated runs.
MAX_CONCURRENT_SUBAGENTS = 4

# Thread pool for background task scheduling and orchestration
_scheduler_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SUBAGENTS,
    thread_name_prefix="subagent-scheduler-",
)

# Thread pool for actual subagent execution (with timeout support)
# Larger pool to avoid blocking when scheduler submits execution tasks
_execution_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SUBAGENTS,
    thread_name_prefix="subagent-exec-",
)


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    """Filter tools based on subagent configuration.

    Args:
        all_tools: List of all available tools.
        allowed: Optional allowlist of tool names. If provided, only these tools are included.
        disallowed: Optional denylist of tool names. These tools are always excluded.

    Returns:
        Filtered list of tools.
    """
    filtered = all_tools

    # Apply allowlist if specified
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # Apply denylist
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


def _get_model_name(config: SubagentConfig, parent_model: str | None) -> str | None:
    """Resolve the model name for a subagent.

    Args:
        config: Subagent configuration.
        parent_model: The parent agent's model name.

    Returns:
        Model name to use, or None to use default.
    """
    if config.model == "inherit":
        return parent_model
    return config.model


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
    ):
        """Initialize the executor.

        Args:
            config: Subagent configuration.
            tools: List of all available tools (will be filtered).
            parent_model: The parent agent's model name for inheritance.
            sandbox_state: Sandbox state from parent agent.
            thread_data: Thread data from parent agent.
            thread_id: Thread ID for sandbox operations.
            trace_id: Trace ID from parent for distributed tracing.
        """
        self.config = config
        self.parent_model = parent_model
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # Generate trace_id if not provided (for top-level calls)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

        # Filter tools based on config
        self.tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")
        log_subtask_event(
            "subagent_executor_initialized",
            trace_id=self.trace_id,
            subagent_name=config.name,
            tool_count=len(self.tools),
            parent_model=parent_model,
            thread_id=thread_id,
        )

    def _create_agent(self):
        """Create the agent instance."""
        model_name = _get_model_name(self.config, self.parent_model)
        model = create_chat_model(name=model_name, thinking_enabled=self.config.thinking_enabled)
        logger.info(
            "[trace=%s] Subagent %s using model=%s thinking_enabled=%s",
            self.trace_id,
            self.config.name,
            model_name,
            self.config.thinking_enabled,
        )

        # Subagents need minimal middlewares to ensure tools can access sandbox and thread_data
        # These middlewares will reuse the sandbox/thread_data from parent agent
        from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from src.sandbox.middleware import SandboxMiddleware

        middlewares = [
            ThreadDataMiddleware(lazy_init=True),  # Compute thread paths
            SandboxMiddleware(lazy_init=True),  # Reuse parent's sandbox (no re-acquisition)
        ]

        return create_agent(
            model=model,
            tools=self.tools,
            middleware=middlewares,
            system_prompt=self.config.system_prompt,
            state_schema=ThreadState,
        )

    def _build_initial_state(self, task: str) -> dict[str, Any]:
        """Build the initial state for agent execution.

        Args:
            task: The task description.

        Returns:
            Initial state dictionary.
        """
        state: dict[str, Any] = {
            "messages": [HumanMessage(content=task)],
        }

        # Pass through sandbox and thread data from parent
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """
        if result_holder is not None:
            # Use the provided result holder (for async execution with real-time updates)
            result = result_holder
        else:
            # Create a new result for synchronous execution
            task_id = str(uuid.uuid4())[:8]
            result = SubagentResult(
                task_id=task_id,
                trace_id=self.trace_id,
                status=SubagentStatus.RUNNING,
                started_at=datetime.now(),
            )

        try:
            agent = self._create_agent()
            state = self._build_initial_state(task)

            # Build config with thread_id for sandbox access and recursion limit
            run_config: RunnableConfig = {
                "recursion_limit": self.config.max_turns,
            }
            context = {}
            if self.thread_id:
                run_config["configurable"] = {"thread_id": self.thread_id}
                context["thread_id"] = self.thread_id

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting execution with max_turns={self.config.max_turns}")

            # Use stream instead of invoke to get real-time updates.
            # `messages` yields incremental AI chunks; `values` gives us the final state.
            final_state = None
            aggregated_chunks: dict[str, AIMessageChunk] = {}
            for mode, payload in agent.stream(  # type: ignore[arg-type]
                state,
                config=run_config,
                context=context,
                stream_mode=["messages", "values"],
            ):
                if mode == "values":
                    final_state = payload
                    continue

                if mode != "messages":
                    continue

                streamed_message, _metadata = payload
                if isinstance(streamed_message, AIMessageChunk):
                    message_id = streamed_message.id or str(uuid.uuid4())
                    previous_chunk = aggregated_chunks.get(message_id)
                    aggregated_chunk = (
                        streamed_message
                        if previous_chunk is None
                        else previous_chunk + streamed_message
                    )
                    aggregated_chunks[message_id] = aggregated_chunk
                    message_dict = _strip_reasoning_from_message_dict(
                        message_chunk_to_message(aggregated_chunk).model_dump()
                    )
                elif isinstance(streamed_message, AIMessage):
                    message_dict = _strip_reasoning_from_message_dict(
                        streamed_message.model_dump()
                    )
                else:
                    continue

                if not result.ai_messages or result.ai_messages[-1] != message_dict:
                    result.ai_messages.append(message_dict)
                    logger.info(
                        f"[trace={self.trace_id}] Subagent {self.config.name} captured AI message snapshot #{len(result.ai_messages)}"
                    )

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed execution")

            if final_state is None:
                logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no final state")
                result.result = "No response generated"
            else:
                # Extract the final message - find the last AIMessage
                messages = final_state.get("messages", [])
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} final messages count: {len(messages)}")

                # Find the last AIMessage in the conversation
                last_ai_message = None
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage):
                        last_ai_message = msg
                        break

                if last_ai_message is not None:
                    content = last_ai_message.content
                    # Handle both str and list content types for the final result
                    if isinstance(content, str):
                        result.result = content
                    elif isinstance(content, list):
                        # Extract text from list of content blocks for final result only
                        text_parts = []
                        for block in content:
                            if isinstance(block, str):
                                text_parts.append(block)
                            elif isinstance(block, dict) and "text" in block:
                                text_parts.append(block["text"])
                        result.result = "\n".join(text_parts) if text_parts else "No text content in response"
                    else:
                        result.result = str(content)
                elif messages:
                    # Fallback: use the last message if no AIMessage found
                    last_message = messages[-1]
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no AIMessage found, using last message: {type(last_message)}")
                    result.result = str(last_message.content) if hasattr(last_message, "content") else str(last_message)
                else:
                    logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} no messages in final state")
                    result.result = "No response generated"

            result.structured_result = _parse_structured_subtask_result(result.result)

            result.status = SubagentStatus.COMPLETED
            result.completed_at = datetime.now()

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            append_error_doc(
                location="subagent_executor.execute",
                summary=f"Subagent {self.config.name} execution failed",
                error=str(e),
                context={
                    "trace_id": self.trace_id,
                    "subagent_name": self.config.name,
                    "task_id": result.task_id,
                },
            )
            result.status = SubagentStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now()

        return result

    def execute_async(self, task: str, task_id: str | None = None) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description for the subagent.
            task_id: Optional task ID to use. If not provided, a random UUID will be generated.

        Returns:
            Task ID that can be used to check status later.
        """
        # Use provided task_id or generate a new one
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        # Create initial pending result
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}, timeout={self.config.timeout_seconds}s")
        log_subtask_event(
            "subtask_async_queued",
            trace_id=self.trace_id,
            task_id=task_id,
            subagent_name=self.config.name,
            timeout_seconds=self.config.timeout_seconds,
        )

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        # Submit to scheduler pool
        def run_task():
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now()
                result_holder = _background_tasks[task_id]
            log_subtask_event(
                "subtask_async_started",
                trace_id=self.trace_id,
                task_id=task_id,
                subagent_name=self.config.name,
            )

            try:
                # Submit execution to execution pool with timeout
                # Pass result_holder so execute() can update it in real-time
                execution_future: Future = _execution_pool.submit(self.execute, task, result_holder)
                try:
                    # Wait for execution with timeout
                    exec_result = execution_future.result(timeout=self.config.timeout_seconds)
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = exec_result.status
                        _background_tasks[task_id].result = exec_result.result
                        _background_tasks[task_id].error = exec_result.error
                        _background_tasks[task_id].completed_at = datetime.now()
                        _background_tasks[task_id].ai_messages = exec_result.ai_messages
                        _background_tasks[task_id].structured_result = exec_result.structured_result
                    log_subtask_event(
                        "subtask_async_finished",
                        trace_id=self.trace_id,
                        task_id=task_id,
                        subagent_name=self.config.name,
                        status=exec_result.status.value,
                        result=exec_result.result,
                        error=exec_result.error,
                        ai_message_count=len(exec_result.ai_messages or []),
                        structured_result=exec_result.structured_result,
                    )
                except FuturesTimeoutError:
                    logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                    append_error_doc(
                        location="subagent_executor.execute_async",
                        summary=f"Subagent {self.config.name} execution timed out",
                        error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                        context={
                            "trace_id": self.trace_id,
                            "subagent_name": self.config.name,
                            "task_id": task_id,
                        },
                    )
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                        _background_tasks[task_id].error = f"Execution timed out after {self.config.timeout_seconds} seconds"
                        _background_tasks[task_id].completed_at = datetime.now()
                    log_subtask_event(
                        "subtask_async_timeout",
                        trace_id=self.trace_id,
                        task_id=task_id,
                        subagent_name=self.config.name,
                        timeout_seconds=self.config.timeout_seconds,
                    )
                    # Cancel the future (best effort - may not stop the actual execution)
                    execution_future.cancel()
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                append_error_doc(
                    location="subagent_executor.execute_async",
                    summary=f"Subagent {self.config.name} async execution failed",
                    error=str(e),
                    context={
                        "trace_id": self.trace_id,
                        "subagent_name": self.config.name,
                        "task_id": task_id,
                    },
                )
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = str(e)
                    _background_tasks[task_id].completed_at = datetime.now()
                log_subtask_event(
                    "subtask_async_failed",
                    trace_id=self.trace_id,
                    task_id=task_id,
                    subagent_name=self.config.name,
                    error=str(e),
                )

        _scheduler_pool.submit(run_task)
        return task_id


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        task_id: The task ID returned by execute_async.

    Returns:
        SubagentResult if found, None otherwise.
    """
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def list_background_tasks() -> list[SubagentResult]:
    """List all background tasks.

    Returns:
        List of all SubagentResult instances.
    """
    with _background_tasks_lock:
        return list(_background_tasks.values())
