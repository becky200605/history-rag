"use client";

import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FilesIcon, XIcon } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import {
  ArtifactFileDetail,
  ArtifactFileList,
  KNOWLEDGE_ARTIFACT_PANEL_DEFAULT_WIDTH,
  KNOWLEDGE_ARTIFACT_PANEL_EXPANDED_WIDTH,
  useArtifacts,
} from "@/components/workspace/artifacts";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { SilkRibbon } from "@/components/workspace/silk-ribbon";
import { SubtaskDetailSheet } from "@/components/workspace/subtask-detail-sheet";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Tooltip } from "@/components/workspace/tooltip";
import { Welcome } from "@/components/workspace/welcome";
import { getAPIClient } from "@/core/api";
import { useI18n } from "@/core/i18n/hooks";
import {
  parseSelectedMaterials,
  type SelectedMaterial,
} from "@/core/knowledge/selection";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import { type AgentThread, type AgentThreadState } from "@/core/threads";
import { useSubmitThread, useThreadStream } from "@/core/threads/hooks";
import {
  buildThreadDisplayMetadata,
  pathOfThread,
  readThreadDisplayMetadata,
  textOfMessage,
  type ThreadDisplayContextSnapshot,
  titleOfThread,
} from "@/core/threads/utils";
import {
  WORKSPACE_TODO_SELECTED_EVENT,
  type Todo,
  type TodoSelectionDetail,
} from "@/core/todos";
import { uuid } from "@/core/utils/uuid";
import { env } from "@/env";
import { cn } from "@/lib/utils";
import { authClient } from "@/server/better-auth/client";

const THREAD_ROUTE_HANDOFF_KEY = "workspace:thread-route-handoff";
const THREAD_ROUTE_HANDOFF_TTL_MS = 15_000;

function readThreadRouteHandoff() {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.sessionStorage.getItem(THREAD_ROUTE_HANDOFF_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as {
      createdAt?: number;
      context?: ThreadDisplayContextSnapshot;
      threadId?: string;
    };
    if (
      typeof parsed.threadId !== "string" ||
      typeof parsed.createdAt !== "number"
    ) {
      window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
      return null;
    }

    if (Date.now() - parsed.createdAt > THREAD_ROUTE_HANDOFF_TTL_MS) {
      window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
      return null;
    }

    return parsed;
  } catch {
    window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
    return null;
  }
}

function rememberThreadRouteHandoff(
  threadId: string,
  context?: ThreadDisplayContextSnapshot,
) {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    THREAD_ROUTE_HANDOFF_KEY,
    JSON.stringify({
      context,
      threadId,
      createdAt: Date.now(),
    }),
  );
}

function clearThreadRouteHandoff(threadId?: string) {
  if (typeof window === "undefined") {
    return;
  }

  const handoff = readThreadRouteHandoff();
  if (!handoff) {
    return;
  }

  if (!threadId || handoff.threadId === threadId) {
    window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
  }
}

type TaskStartedEvent = {
  type: "task_started";
  task_id: string;
  description?: string;
};

type TaskRunningEvent = {
  type: "task_running";
  task_id: string;
  message: AIMessage;
};

type TaskCompletedEvent = {
  type: "task_completed";
  task_id: string;
  result?: string;
  summary?: string;
  findings?: string[];
  citations?: string[];
  open_questions?: string[];
};

type TaskFailedEvent = {
  type: "task_failed" | "task_timed_out";
  task_id: string;
  error?: string;
};

type TodoBoardUpdatedEvent = {
  type: "todo_board_updated";
  todos: Todo[];
};

function isTaskStartedEvent(event: unknown): event is TaskStartedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_started" &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTaskRunningEvent(event: unknown): event is TaskRunningEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_running" &&
    "task_id" in event &&
    typeof event.task_id === "string" &&
    "message" in event &&
    typeof event.message === "object" &&
    event.message !== null
  );
}

function isTaskCompletedEvent(event: unknown): event is TaskCompletedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_completed" &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTaskFailedEvent(event: unknown): event is TaskFailedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    (event.type === "task_failed" || event.type === "task_timed_out") &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTodoBoardUpdatedEvent(event: unknown): event is TodoBoardUpdatedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "todo_board_updated" &&
    "todos" in event &&
    Array.isArray(event.todos)
  );
}

function normalizeTodoContent(content?: string | null) {
  if (!content) {
    return "";
  }

  return content
    .replace(/\s+/g, " ")
    .replace(/（/g, "(")
    .replace(/）/g, ")")
    .replace(/：/g, ":")
    .trim();
}

function todosMatch(left: Todo | null | undefined, right: Todo | null | undefined) {
  if (!left || !right) {
    return false;
  }

  if (left.task_id && right.task_id && left.task_id === right.task_id) {
    return true;
  }

  if (left.id && right.id && left.id === right.id) {
    return true;
  }

  const leftContent = normalizeTodoContent(left.content);
  const rightContent = normalizeTodoContent(right.content);
  if (!leftContent || !rightContent) {
    return false;
  }

  return (
    leftContent === rightContent ||
    leftContent.includes(rightContent) ||
    rightContent.includes(leftContent)
  );
}

function mergeStreamingMessages(
  previousMessages: AIMessage[] | undefined,
  incomingMessages: AIMessage[],
) {
  const merged = [...(previousMessages ?? [])];

  for (const incoming of incomingMessages) {
    const incomingId = incoming.id;
    if (!incomingId) {
      merged.push(incoming);
      continue;
    }

    const existingIndex = merged.findIndex((message) => message.id === incomingId);
    if (existingIndex >= 0) {
      merged[existingIndex] = incoming;
      continue;
    }

    merged.push(incoming);
  }

  return merged;
}

function mergeTaskEventIntoTodos(
  todos: Todo[] | null,
  event:
    | TaskStartedEvent
    | TaskRunningEvent
    | TaskCompletedEvent
    | TaskFailedEvent,
) {
  if (!todos || todos.length === 0) {
    return todos;
  }

  let changed = false;
  const nextTodos = todos.map((todo) => {
    if (todo.task_id !== event.task_id) {
      return todo;
    }

    changed = true;
    if (event.type === "task_started") {
      return {
        ...todo,
        status: "in_progress" as const,
        task_description: event.description ?? todo.task_description ?? todo.content,
      };
    }

    if (event.type === "task_running") {
      return {
        ...todo,
        status: "in_progress" as const,
        latest_message: event.message,
        stream_messages: mergeStreamingMessages(
          todo.stream_messages,
          [event.message],
        ),
      };
    }

    if (event.type === "task_completed") {
      return {
        ...todo,
        status: "completed" as const,
        result: event.result,
        result_summary: event.summary ?? event.result ?? todo.result_summary,
        structured_summary: event.summary ?? todo.structured_summary,
        structured_findings: event.findings ?? todo.structured_findings,
        structured_citations: event.citations ?? todo.structured_citations,
        structured_gaps: event.open_questions ?? todo.structured_gaps,
      };
    }

    return {
      ...todo,
      status: "failed" as const,
      error: event.error ?? todo.error,
    };
  });

  return changed ? nextTodos : todos;
}

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const isNewThread = threadIdFromPath === "new";
  const { data: session, isPending: isSessionPending } =
    authClient.useSession();
  const shouldKeepContentDuringAccessCheck = useMemo(() => {
    if (isNewThread) {
      return false;
    }

    return readThreadRouteHandoff()?.threadId === threadIdFromPath;
  }, [isNewThread, threadIdFromPath]);
  const selectedMaterials = useMemo(
    () => parseSelectedMaterials(searchParams.get("materials")),
    [searchParams],
  );
  const selectedMaterialScopes = useMemo(
    () =>
      Array.from(
        new Set(
          selectedMaterials
            .map((item) => item.scope ?? "global")
            .filter(
              (scope): scope is "global" | "thread" | "user" =>
                scope === "global" || scope === "thread" || scope === "user",
            ),
        ),
      ),
    [selectedMaterials],
  );

  const accessQuery = useQuery({
    queryKey: ["thread", "access", threadIdFromPath, session?.user.id],
    enabled:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
      (Boolean(session?.user.id) && !isSessionPending && !isNewThread),
    queryFn: async () => {
      const thread =
        await getAPIClient().threads.get<AgentThreadState>(threadIdFromPath);
      queryClient.setQueryData(
        ["thread", "details", threadIdFromPath, session?.user.id],
        thread,
      );
      const ownerId =
        typeof thread.metadata?.user_id === "string"
          ? thread.metadata.user_id
          : undefined;

      if (!ownerId && session?.user.id) {
        await getAPIClient().threads.update(threadIdFromPath, {
          metadata: {
            ...thread.metadata,
            user_id: session.user.id,
          },
        });
        return true;
      }

      return ownerId === session?.user.id;
    },
    retry: false,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || isNewThread) {
      return;
    }

    if (accessQuery.data === false || accessQuery.isError) {
      void router.replace("/workspace/chats");
    }
  }, [accessQuery.data, accessQuery.isError, isNewThread, router]);

  useEffect(() => {
    if (!shouldKeepContentDuringAccessCheck) {
      return;
    }

    if (accessQuery.data !== undefined || accessQuery.isError) {
      clearThreadRouteHandoff(threadIdFromPath);
    }
  }, [
    accessQuery.data,
    accessQuery.isError,
    shouldKeepContentDuringAccessCheck,
    threadIdFromPath,
  ]);

  if (
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
    !isNewThread &&
    (isSessionPending ||
      (!shouldKeepContentDuringAccessCheck && accessQuery.isPending) ||
      accessQuery.data === false)
  ) {
    return null;
  }

  return (
    <ChatPageContent
      initialThreadIdFromPath={threadIdFromPath}
      selectedMaterials={selectedMaterials}
      selectedMaterialScopes={selectedMaterialScopes}
    />
  );
}

function ChatPageContent({
  initialThreadIdFromPath,
  selectedMaterials,
  selectedMaterialScopes,
}: {
  initialThreadIdFromPath: string;
  selectedMaterials: SelectedMaterial[];
  selectedMaterialScopes: Array<"global" | "thread" | "user">;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const apiClient = getAPIClient();
  const { data: session } = authClient.useSession();
  const [settings, setSettings] = useLocalSettings();
  const { models } = useModels();
  const { setOpen: setSidebarOpen } = useSidebar();
  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    selectedArtifact,
  } = useArtifacts();
  const searchParams = useSearchParams();
  const promptInputController = usePromptInputController();
  const didNavigateForCreatedRunRef = useRef(false);
  const inputInitialValue = useMemo(() => {
    if (
      initialThreadIdFromPath !== "new" ||
      searchParams.get("mode") !== "skill"
    ) {
      return undefined;
    }
    return t.inputBox.createSkillPrompt;
  }, [initialThreadIdFromPath, searchParams, t.inputBox.createSkillPrompt]);
  const lastInitialValueRef = useRef<string | undefined>(undefined);
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;
  useEffect(() => {
    if (
      inputInitialValue &&
      inputInitialValue !== lastInitialValueRef.current
    ) {
      lastInitialValueRef.current = inputInitialValue;
      setTimeout(() => {
        setInputRef.current(inputInitialValue);
        const textarea = document.querySelector("textarea");
        if (textarea) {
          textarea.focus();
          textarea.selectionStart = textarea.value.length;
          textarea.selectionEnd = textarea.value.length;
        }
      }, 100);
    }
  }, [inputInitialValue]);
  const isNewThread = useMemo(
    () => initialThreadIdFromPath === "new",
    [initialThreadIdFromPath],
  );
  const initialRouteHandoff = useMemo(() => {
    if (initialThreadIdFromPath === "new") {
      return null;
    }

    const handoff = readThreadRouteHandoff();
    return handoff?.threadId === initialThreadIdFromPath ? handoff : null;
  }, [initialThreadIdFromPath]);
  const [threadId, setThreadId] = useState<string | null>(null);
  useEffect(() => {
    if (initialThreadIdFromPath !== "new") {
      setThreadId(initialThreadIdFromPath);
    } else {
      setThreadId(uuid());
    }
  }, [initialThreadIdFromPath]);

  const { showNotification } = useNotification();
  const threadDetailsQuery = useQuery({
    queryKey: ["thread", "details", threadId, session?.user.id],
    enabled:
      !!threadId &&
      !isNewThread &&
      (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || !!session?.user.id),
    queryFn: async () => apiClient.threads.get<AgentThreadState>(threadId!),
    staleTime: 30_000,
  });
  const [finalState, setFinalState] = useState<AgentThreadState | null>(null);
  const threadMetadataContext = useMemo(
    () => readThreadDisplayMetadata(threadDetailsQuery.data?.metadata),
    [threadDetailsQuery.data?.metadata],
  );
  const persistedContext = useMemo(
    () => threadMetadataContext ?? initialRouteHandoff?.context ?? null,
    [initialRouteHandoff?.context, threadMetadataContext],
  );
  const baseContext = useMemo(
    () => ({
      ...settings.context,
      ...persistedContext,
    }),
    [persistedContext, settings.context],
  );
  const [liveTodos, setLiveTodos] = useState<Todo[] | null>(null);
  const [selectedTodoId, setSelectedTodoId] = useState<string | null>(null);
  const [selectedTodoDraft, setSelectedTodoDraft] = useState<Todo | null>(null);
  const selectTodo = useCallback((todo: Todo | null) => {
    if (!todo) {
      setSelectedTodoId(null);
      setSelectedTodoDraft(null);
      return;
    }

    setSelectedTodoDraft(todo);
    setSelectedTodoId(todo.id ?? todo.task_id ?? null);
  }, []);
  const thread = useThreadStream({
    isNewThread,
    threadId,
    onCreated(run) {
      if (!isNewThread || didNavigateForCreatedRunRef.current) {
        return;
      }
      didNavigateForCreatedRunRef.current = true;
      rememberThreadRouteHandoff(run.thread_id, resolvedContext);
      if (
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
        session?.user.id
      ) {
        void apiClient
          .threads
          .update(run.thread_id, {
            metadata: {
              user_id: session.user.id,
              ...buildThreadDisplayMetadata(resolvedContext),
            },
          })
          .catch((error) => {
            console.error("Failed to persist thread display context:", error);
          });
      }
      const currentQuery = searchParams.toString();
      router.push(
        currentQuery
          ? `${pathOfThread(run.thread_id)}?${currentQuery}`
          : pathOfThread(run.thread_id),
      );
    },
    onFinish: (state) => {
      setLiveTodos(state.todos ?? null);
      setFinalState(state);
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages[state.messages.length - 1];
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            if (textContent.length > 200) {
              body = textContent.substring(0, 200) + "...";
            } else {
              body = textContent;
            }
          }
        }
        showNotification(state.title, {
          body,
        });
      }
    },
    onCustomEvent: (event) => {
      if (isTodoBoardUpdatedEvent(event)) {
        setLiveTodos((currentTodos) => {
          const eventTodos = event.todos;
          if (!currentTodos || currentTodos.length === 0) {
            return eventTodos;
          }

          return eventTodos.map((todo) => {
            const currentTodo =
              currentTodos.find((candidate) => todosMatch(candidate, todo)) ??
              null;
            if (!currentTodo) {
              return todo;
            }

            return {
              ...currentTodo,
              ...todo,
              stream_messages: todo.stream_messages ?? currentTodo.stream_messages,
              latest_message: todo.latest_message ?? currentTodo.latest_message,
              result: todo.result ?? currentTodo.result,
              structured_summary:
                todo.structured_summary ?? currentTodo.structured_summary,
              structured_findings:
                todo.structured_findings ?? currentTodo.structured_findings,
              structured_citations:
                todo.structured_citations ?? currentTodo.structured_citations,
              structured_gaps:
                todo.structured_gaps ?? currentTodo.structured_gaps,
              task_description:
                todo.task_description ?? currentTodo.task_description,
            };
          });
        });
        if (event.todos.length > 0) {
          setTodoListCollapsed(false);
        }
        return;
      }

      if (isTaskStartedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskRunningEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskCompletedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskFailedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
      }
    },
  }) as unknown as UseStream<AgentThreadState>;
  useEffect(() => {
    if (thread.isLoading) setFinalState(null);
  }, [thread.isLoading]);

  const title = useMemo(() => {
    let result = isNewThread
      ? ""
      : titleOfThread(thread as unknown as AgentThread);
    if (result === "Untitled") {
      result = "";
    }
    return result;
  }, [thread, isNewThread]);

  useEffect(() => {
    const pageTitle = isNewThread
      ? t.pages.newChat
      : thread.values?.title && thread.values.title !== "Untitled"
        ? thread.values.title
        : t.pages.untitled;
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${pageTitle} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.values.title,
    thread.isThreadLoading,
  ]);

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  const [artifactCompareOpen, setArtifactCompareOpen] = useState(false);
  useEffect(() => {
    setArtifacts(thread.values.artifacts);
    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (thread?.values?.artifacts?.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(thread.values.artifacts[0]!);
      }
    }
  }, [
    autoSelectFirstArtifact,
    selectArtifact,
    setArtifacts,
    thread.values.artifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const handleKnowledgeCompareToggle = useCallback((open: boolean) => {
    setArtifactCompareOpen(open);
  }, []);

  useEffect(() => {
    if (!artifactPanelOpen) {
      setArtifactCompareOpen(false);
    }
  }, [artifactPanelOpen]);

  const [todoListCollapsed, setTodoListCollapsed] = useState(false);
  const displayedTodos = useMemo(
    () => liveTodos ?? thread.values.todos ?? [],
    [liveTodos, thread.values.todos],
  );
  const hasActiveTodos = useMemo(
    () =>
      displayedTodos.some(
        (todo) => todo.status === "pending" || todo.status === "in_progress",
      ),
    [displayedTodos],
  );

  const selectedTodo = useMemo(() => {
    const selectedById = selectedTodoId
      ? displayedTodos.find(
          (todo) => (todo.id ?? todo.task_id ?? null) === selectedTodoId,
        ) ?? null
      : null;

    if (selectedById) {
      return selectedById;
    }

    if (!selectedTodoDraft) {
      return null;
    }

    return (
      displayedTodos.find((todo) => {
        return todosMatch(selectedTodoDraft, todo);
      }) ?? selectedTodoDraft
    );
  }, [displayedTodos, selectedTodoDraft, selectedTodoId]);

  useEffect(() => {
    if (!selectedTodoDraft && !selectedTodoId) {
      return;
    }

    const matchedTodo = displayedTodos.find((todo) => {
      if (selectedTodoId && (todo.id ?? todo.task_id ?? null) === selectedTodoId) {
        return true;
      }

      if (!selectedTodoDraft) {
        return false;
      }

      return todosMatch(selectedTodoDraft, todo);
    });

    if (matchedTodo) {
      setSelectedTodoDraft(matchedTodo);
      if (!selectedTodoId && (matchedTodo.id ?? matchedTodo.task_id ?? null)) {
        setSelectedTodoId(matchedTodo.id ?? matchedTodo.task_id ?? null);
      }
    }
  }, [displayedTodos, selectedTodoDraft, selectedTodoId]);

  useEffect(() => {
    if (displayedTodos.length > 0 && hasActiveTodos) {
      setTodoListCollapsed(false);
    }
  }, [displayedTodos.length, hasActiveTodos]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const handleTodoSelected = (event: Event) => {
      const { detail } = event as CustomEvent<TodoSelectionDetail>;
      selectTodo(detail.todo);
      setTodoListCollapsed(false);
    };

    window.addEventListener(
      WORKSPACE_TODO_SELECTED_EVENT,
      handleTodoSelected as EventListener,
    );

    return () => {
      window.removeEventListener(
        WORKSPACE_TODO_SELECTED_EVENT,
        handleTodoSelected as EventListener,
      );
    };
  }, [selectTodo]);

  const resolvedModelName = useMemo(() => {
    if (models.length === 0) {
      return baseContext.model_name;
    }

    return (
      models.find((model) => model.name === baseContext.model_name)?.name ??
      models[0]?.name
    );
  }, [baseContext.model_name, models]);

  const resolvedContext = useMemo(
    () => ({
      ...baseContext,
      model_name: resolvedModelName,
    }),
    [baseContext, resolvedModelName],
  );

  const threadContext = useMemo(
    () => ({
      model_name: resolvedContext.model_name,
      thinking_enabled:
        resolvedContext.scenario === "research" ||
        (resolvedContext.scenario === "qa" && resolvedContext.tier === "pro"),
      is_plan_mode: resolvedContext.scenario === "research",
      max_concurrent_subagents: 4,
      subagent_enabled: true,
      qa_mode: resolvedContext.scenario === "qa",
      concise_answers:
        resolvedContext.scenario === "qa" && resolvedContext.tier === "ultra",
      selected_doc_ids: selectedMaterials.map((item) => item.doc_id),
      selected_sources_scope: selectedMaterialScopes,
      selected_materials: selectedMaterials,
    }),
    [resolvedContext, selectedMaterialScopes, selectedMaterials],
  );

  useEffect(() => {
    if (persistedContext) {
      return;
    }
    if (
      resolvedModelName &&
      settings.context.model_name !== resolvedModelName
    ) {
      setSettings("context", {
        model_name: resolvedModelName,
      });
    }
  }, [
    persistedContext,
    resolvedModelName,
    setSettings,
    settings.context.model_name,
  ]);

  const submitThread = useSubmitThread({
    isNewThread,
    threadId,
    thread,
    threadContext,
    displayContext: resolvedContext,
  });
  const handleSubmit = useCallback(
    async (...args: Parameters<typeof submitThread>) => {
      setLiveTodos(null);
      await submitThread(...args);
    },
    [submitThread],
  );
  const handleStop = useCallback(async () => {
    const currentThreadId = threadId;
    try {
      if (currentThreadId) {
        await getAPIClient().threads.updateState(currentThreadId, {
          values: {
            subtasks_cancel_requested_at: new Date().toISOString(),
          },
        });
      }
    } catch (error) {
      console.error("Failed to mark subtasks for cancellation:", error);
    } finally {
      await thread.stop();
    }
  }, [thread, threadId]);

  const handleSelectTodo = useCallback((todo: Todo) => {
    selectTodo(todo);
    setTodoListCollapsed(false);
  }, [selectTodo]);

  if (!threadId) {
    return null;
  }

  return (
    <ThreadContext.Provider value={{ threadId, thread }}>
      <div className="flex size-full min-h-0">
        <div className="relative min-w-0 flex-1">
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-14 shrink-0 items-center px-4",
                isNewThread
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur",
              )}
            >
              <div className="flex w-full items-center text-sm font-medium">
                {title !== "Untitled" && (
                  <ThreadTitle threadId={threadId} threadTitle={title} />
                )}
              </div>
              <div>
                {artifacts?.length > 0 && !artifactsOpen && (
                  <Tooltip content="Show artifacts of this conversation">
                    <Button
                      className="text-muted-foreground hover:text-foreground"
                      variant="ghost"
                      onClick={() => {
                        setArtifactsOpen(true);
                        setSidebarOpen(false);
                      }}
                    >
                      <FilesIcon />
                      {t.common.artifacts}
                    </Button>
                  </Tooltip>
                )}
              </div>
            </header>
            <main className="relative flex min-h-0 max-w-full grow flex-col">
              <div className="flex size-full justify-center">
                  <MessageList
                    className={cn("size-full", !isNewThread && "pt-14")}
                    threadId={threadId}
                    thread={thread}
                    messagesOverride={
                      !thread.isLoading && finalState?.messages
                        ? (finalState.messages as Message[])
                        : undefined
                    }
                    paddingBottom={todoListCollapsed ? 140 : 400}
                  />
                </div>
                <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                  <div
                    className={cn(
                      "relative w-full mb-4",
                      isNewThread && "-translate-y-[calc(50vh-96px)]",
                      isNewThread
                        ? "max-w-(--container-width-sm)"
                        : "max-w-(--container-width-md)",
                    )}
                  >
                    <div className="absolute bottom-full right-0 left-0 mb-1 z-0">
                      <TodoList
                        todos={displayedTodos}
                        collapsed={todoListCollapsed}
                        selectedTodoId={selectedTodoId}
                        hidden={displayedTodos.length === 0}
                        onSelectTodo={handleSelectTodo}
                        onToggle={() =>
                          setTodoListCollapsed(!todoListCollapsed)
                        }
                      />
                    </div>
                    <InputBox
                      className={cn("w-full shadow-2xl")}
                    isNewThread={isNewThread}
                    autoFocus={isNewThread}
                    status={thread.isLoading ? "streaming" : "ready"}
                    context={resolvedContext}
                    selectedMaterials={selectedMaterials}
                    extraHeader={
                      isNewThread && (
                        <Welcome
                          scenario={resolvedContext.scenario}
                          tier={resolvedContext.tier}
                        />
                      )
                    }
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    onContextChange={(context) =>
                      setSettings("context", context)
                    }
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                  {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                    <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                      {t.common.notAvailableInDemoMode}
                    </div>
                  )}
                </div>
              </div>
              
              {isNewThread && <SilkRibbon />}
            </main>
          </div>
        </div>
        {artifactPanelOpen && (
          <div
            className="bg-background relative z-40 h-full shrink-0 border-l p-4"
            style={{
              width: artifactCompareOpen
                ? `min(${KNOWLEDGE_ARTIFACT_PANEL_EXPANDED_WIDTH}px, calc(100vw - 24px))`
                : `${KNOWLEDGE_ARTIFACT_PANEL_DEFAULT_WIDTH}px`,
            }}
          >
            {selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
                onKnowledgeCompareToggle={handleKnowledgeCompareToggle}
              />
            ) : (
              <div className="relative flex size-full justify-center">
                <div className="absolute top-1 right-1 z-30">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => {
                      setArtifactsOpen(false);
                    }}
                  >
                    <XIcon />
                  </Button>
                </div>
                {thread.values.artifacts?.length === 0 ? (
                  <ConversationEmptyState
                    icon={<FilesIcon />}
                    title="No artifact selected"
                    description="Select an artifact to view its details"
                  />
                ) : (
                  <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
                    <header className="shrink-0">
                      <h2 className="text-lg font-medium">Artifacts</h2>
                    </header>
                    <main className="min-h-0 grow">
                      <ArtifactFileList
                        className="max-w-(--container-width-sm) p-4 pt-12"
                        files={thread.values.artifacts ?? []}
                        threadId={threadId}
                      />
                    </main>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <SubtaskDetailSheet
          open={selectedTodo !== null}
          todo={selectedTodo}
          onOpenChange={(open) => {
            if (!open) {
              selectTodo(null);
            }
          }}
        />
      </div>
    </ThreadContext.Provider>
  );
}
