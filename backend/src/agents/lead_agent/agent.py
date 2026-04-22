import logging

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig

from src.agents.lead_agent.prompt import apply_prompt_template
from src.agents.middlewares.citation_enforcement_middleware import CitationEnforcementMiddleware
from src.agents.middlewares.clarification_middleware import ClarificationMiddleware
from src.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from src.agents.middlewares.knowledge_checkpoint_middleware import KnowledgeCheckpointMiddleware
from src.agents.middlewares.knowledge_directory_middleware import KnowledgeDirectoryMiddleware
from src.agents.middlewares.memory_middleware import MemoryMiddleware
from src.agents.middlewares.output_aware_summarization_middleware import OutputAwareSummarizationMiddleware
from src.agents.middlewares.parallel_todo_list_middleware import TodoListMiddleware
from src.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from src.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
from src.agents.middlewares.title_middleware import TitleMiddleware
from src.agents.middlewares.uploads_middleware import UploadsMiddleware
from src.agents.middlewares.view_image_middleware import ViewImageMiddleware
from src.agents.thread_state import ThreadState
from src.config.app_config import get_app_config
from src.config.summarization_config import get_summarization_config
from src.models import create_chat_model
from src.sandbox.middleware import SandboxMiddleware
from src.utils.error_logging import configure_persistent_error_logging

logger = logging.getLogger(__name__)


def _resolve_model_name(requested_model_name: str | None) -> str:
    """Resolve a runtime model name safely, falling back to default if invalid. Returns None if no models are configured."""
    app_config = get_app_config()
    default_model_name = app_config.models[0].name if app_config.models else None
    if default_model_name is None:
        raise ValueError(
            "No chat models are configured. Please configure at least one model in config.yaml."
        )

    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name

    if requested_model_name and requested_model_name != default_model_name:
        logger.warning(f"Model '{requested_model_name}' not found in config; fallback to default model '{default_model_name}'.")
    return default_model_name


def _create_summarization_middleware() -> OutputAwareSummarizationMiddleware | None:
    """Create and configure the summarization middleware from config."""
    config = get_summarization_config()

    if not config.enabled:
        return None

    # Prepare trigger parameter
    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    # Prepare keep parameter
    keep = config.keep.to_tuple()

    # Prepare model parameter
    if config.model_name:
        model = config.model_name
    else:
        # Use a lightweight model for summarization to save costs
        # Falls back to default model if not explicitly specified
        model = create_chat_model(thinking_enabled=False)

    # Prepare kwargs
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize

    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    return OutputAwareSummarizationMiddleware(**kwargs)


def _create_todo_list_middleware(
    is_plan_mode: bool,
    *,
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
) -> TodoListMiddleware | None:
    """Create and configure the TodoList middleware.

    Args:
        is_plan_mode: Whether to enable plan mode with TodoList middleware.
        subagent_enabled: Whether subagent/task execution is available for parallel work.
        max_concurrent_subagents: Maximum number of parallel subagent tasks allowed.

    Returns:
        TodoListMiddleware instance if plan mode is enabled, None otherwise.
    """
    if not is_plan_mode:
        return None

    parallel_hint = ""
    if subagent_enabled:
        parallel_hint = f"""
- Treat the todo list as an execution board, not a sequential outline
- When there are multiple independent tasks, prefer a parallel batch over single-threaded exploration
- For historical / multi-book retrieval tasks, if several `书名 × 信息目标` items are independent, mark the current batch (up to {max_concurrent_subagents}) as `in_progress` together and launch matching parallel `task` calls in the SAME response
- Each launched `task` should usually correspond to one active todo item; keep the `task.description` closely aligned with the todo text
- After a batch returns, mark the finished todo items `completed` immediately, then move the next batch to `in_progress`
"""

    # Custom prompts matching DeerFlow's style
    system_prompt = f"""
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep one or more tasks as `in_progress` according to the real execution plan; do NOT force exactly one active task when parallel work is appropriate
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly

**When to Use:**
This tool is designed for complex objectives that require systematic tracking:
- Complex multi-step tasks requiring 3+ distinct steps
- Non-trivial tasks needing careful planning and execution
- User explicitly requests a todo list
- User provides multiple tasks (numbered or comma-separated list)
- The plan may need revisions based on intermediate results

**When NOT to Use:**
- Single, straightforward tasks
- Trivial tasks (< 3 steps)
- Purely conversational or informational requests
- Simple tool calls where the approach is obvious

**Best Practices:**
- Break down complex tasks into smaller, actionable steps
- Use clear, descriptive task names
- Remove tasks that become irrelevant
- Add new tasks discovered during implementation
- Don't be afraid to revise the todo list as you learn more
- For historical / multi-book retrieval tasks, write todo items as `书名 × 信息目标` pairs so the reading route is explicit
- Reflect book coverage in the todo list when relevant: which books are already checked, which books are still pending, and which book you are going to inspect next
- If subagent mode is available and several books can be searched independently, you may turn multiple `书名 × 信息目标` todo items into parallel `task` calls; default to one book per subagent for the first pass, then synthesize centrally
{parallel_hint}

**Task Management:**
Writing todos takes time and tokens - use it when helpful for managing complex problems, not for simple requests.
</todo_list_system>
"""

    tool_description = f"""Use this tool to create and manage a structured task list for complex work sessions.

**IMPORTANT: Only use this tool for complex tasks (3+ steps). For simple requests, just do the work directly.**

## When to Use

Use this tool in these scenarios:
1. **Complex multi-step tasks**: When a task requires 3 or more distinct steps or actions
2. **Non-trivial tasks**: Tasks requiring careful planning or multiple operations
3. **User explicitly requests todo list**: When the user directly asks you to track tasks
4. **Multiple tasks**: When users provide a list of things to be done
5. **Dynamic planning**: When the plan may need updates based on intermediate results

## When NOT to Use

Skip this tool when:
1. The task is straightforward and takes less than 3 steps
2. The task is trivial and tracking provides no benefit
3. The task is purely conversational or informational
4. It's clear what needs to be done and you can just do it

## How to Use

1. **Starting a task**: Mark it as `in_progress` BEFORE beginning work
2. **Completing a task**: Mark it as `completed` IMMEDIATELY after finishing
3. **Updating the list**: Add new tasks, remove irrelevant ones, or update descriptions as needed
4. **Multiple updates**: You can make several updates at once (e.g., complete one task and start the next)
5. **Parallel batches**: When tasks are independent, mark multiple items as `in_progress` together so the todo list matches the real execution batch

## Task States

- `pending`: Task not yet started
- `in_progress`: Currently working on; use multiple active items when parallel execution is the real plan
- `completed`: Task finished successfully

## Task Completion Requirements

**CRITICAL: Only mark a task as completed when you have FULLY accomplished it.**

Never mark a task as completed if:
- There are unresolved issues or errors
- Work is partial or incomplete
- You encountered blockers preventing completion
- You couldn't find necessary resources or dependencies
- Quality standards haven't been met

If blocked, keep the task as `in_progress` and create a new task describing what needs to be resolved.

## Best Practices

- Create specific, actionable items
- Break complex tasks into smaller, manageable steps
- Use clear, descriptive task names
- Update task status in real-time as you work
- Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
- Remove tasks that are no longer relevant
- For historical or knowledge-base retrieval tasks, prefer todo items like `读《某书》：查某问题` instead of vague items like `继续检索`
- If the task involves multiple books, let the todo list show the reading route: which book is already covered, which book remains pending, and which book you will search next
- If subagent mode is enabled and the relevant books are independent enough, convert several pending `读《某书》：查某问题` items into parallel `task` calls; each subagent should usually own one book and return findings plus citation lines, then the lead agent merges them
- **IMPORTANT**: When you write the todo list, mark your first task(s) or first parallel batch as `in_progress` immediately
- **IMPORTANT**: Unless all tasks are completed, always have at least one task `in_progress` to show progress
{parallel_hint}

Being proactive with task management demonstrates thoroughness and ensures all requirements are completed successfully.

**Remember**: If you only need a few tool calls to complete a task and it's clear what to do, it's better to just do the task directly and NOT use this tool at all.
"""

    return TodoListMiddleware(
        system_prompt=system_prompt,
        tool_description=tool_description,
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
    )


# ThreadDataMiddleware must be before SandboxMiddleware to ensure thread_id is available
# UploadsMiddleware should be after ThreadDataMiddleware to access thread_id
# DanglingToolCallMiddleware patches missing ToolMessages before model sees the history
# KnowledgeCheckpointMiddleware compresses old knowledge_search / knowledge_locate payloads
# SummarizationMiddleware should be early to reduce context before other processing
# TodoListMiddleware should be before ClarificationMiddleware to allow todo management
# TitleMiddleware generates title after first exchange
# MemoryMiddleware queues conversation for memory update (after TitleMiddleware)
# ViewImageMiddleware should be before ClarificationMiddleware to inject image details before LLM
# ClarificationMiddleware should be last to intercept clarification requests after model calls
def _build_middlewares(config: RunnableConfig, model_name: str | None):
    """Build middleware chain based on runtime configuration.

    Args:
        config: Runtime configuration containing configurable options like is_plan_mode.

    Returns:
        List of middleware instances.
    """
    middlewares = [
        ThreadDataMiddleware(),
        UploadsMiddleware(),
        KnowledgeDirectoryMiddleware(),
        SandboxMiddleware(),
        DanglingToolCallMiddleware(),
        KnowledgeCheckpointMiddleware(),
        CitationEnforcementMiddleware(),
    ]

    # Add summarization middleware if enabled
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # Add TodoList middleware if plan mode is enabled
    configurable = config.get("configurable", {})
    is_plan_mode = configurable.get("is_plan_mode", False)
    subagent_enabled = configurable.get("subagent_enabled", False)
    max_concurrent_subagents = configurable.get("max_concurrent_subagents", 3)
    todo_list_middleware = _create_todo_list_middleware(
        is_plan_mode,
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
    )
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # Add TitleMiddleware
    middlewares.append(TitleMiddleware())

    # Add MemoryMiddleware (after TitleMiddleware)
    middlewares.append(MemoryMiddleware())

    # Add ViewImageMiddleware only if the current model supports vision.
    # Use the resolved runtime model_name from make_lead_agent to avoid stale config values.
    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # Add SubagentLimitMiddleware to truncate excess parallel task calls
    subagent_enabled = configurable.get("subagent_enabled", False)
    if subagent_enabled:
        max_concurrent_subagents = configurable.get("max_concurrent_subagents", 3)
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))

    # ClarificationMiddleware should always be last
    middlewares.append(ClarificationMiddleware())
    return middlewares


def make_lead_agent(config: RunnableConfig):
    configure_persistent_error_logging()
    # Lazy import to avoid circular dependency
    from src.tools import get_available_tools

    thinking_enabled = config.get("configurable", {}).get("thinking_enabled", True)
    requested_model_name = config.get("configurable", {}).get("model_name") or config.get("configurable", {}).get("model")
    model_name = _resolve_model_name(requested_model_name)
    if model_name is None:
        raise ValueError(
            "No chat model could be resolved. Please configure at least one model in "
            "config.yaml or provide a valid 'model_name'/'model' in the request."
        )
    is_plan_mode = config.get("configurable", {}).get("is_plan_mode", False)
    subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
    max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
    qa_mode = config.get("configurable", {}).get("qa_mode", False)
    concise_answers = config.get("configurable", {}).get("concise_answers", False)

    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None
    if thinking_enabled and model_config is not None and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it; fallback to non-thinking mode.")
        thinking_enabled = False

    logger.info(
        "thinking_enabled: %s, model_name: %s, is_plan_mode: %s, subagent_enabled: %s, max_concurrent_subagents: %s, "
        "qa_mode: %s, concise_answers: %s",
        thinking_enabled,
        model_name,
        is_plan_mode,
        subagent_enabled,
        max_concurrent_subagents,
        qa_mode,
        concise_answers,
    )

    # Inject run metadata for LangSmith trace tagging
    if "metadata" not in config:
        config["metadata"] = {}
    config["metadata"].update(
        {
            "model_name": model_name or "default",
            "thinking_enabled": thinking_enabled,
            "is_plan_mode": is_plan_mode,
            "subagent_enabled": subagent_enabled,
            "qa_mode": qa_mode,
            "concise_answers": concise_answers,
        }
    )

    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
        tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled),
        middleware=_build_middlewares(config, model_name=model_name),
        system_prompt=apply_prompt_template(
            subagent_enabled=subagent_enabled,
            max_concurrent_subagents=max_concurrent_subagents,
            qa_mode=qa_mode,
            concise_answers=concise_answers,
        ),
        state_schema=ThreadState,
    )
