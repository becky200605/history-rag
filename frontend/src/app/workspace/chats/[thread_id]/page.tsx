"use client";

import type { Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useQuery } from "@tanstack/react-query";
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
  pathOfThread,
  textOfMessage,
  titleOfThread,
} from "@/core/threads/utils";
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

function rememberThreadRouteHandoff(threadId: string) {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    THREAD_ROUTE_HANDOFF_KEY,
    JSON.stringify({
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

export default function ChatPage() {
  const router = useRouter();
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
  const [threadId, setThreadId] = useState<string | null>(null);
  useEffect(() => {
    if (initialThreadIdFromPath !== "new") {
      setThreadId(initialThreadIdFromPath);
    } else {
      setThreadId(uuid());
    }
  }, [initialThreadIdFromPath]);

  const { showNotification } = useNotification();
  const [finalState, setFinalState] = useState<AgentThreadState | null>(null);
  const thread = useThreadStream({
    isNewThread,
    threadId,
    onCreated(run) {
      if (!isNewThread || didNavigateForCreatedRunRef.current) {
        return;
      }
      didNavigateForCreatedRunRef.current = true;
      rememberThreadRouteHandoff(run.thread_id);
      const currentQuery = searchParams.toString();
      router.push(
        currentQuery
          ? `${pathOfThread(run.thread_id)}?${currentQuery}`
          : pathOfThread(run.thread_id),
      );
    },
    onFinish: (state) => {
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

  const [todoListCollapsed, setTodoListCollapsed] = useState(true);

  const resolvedModelName = useMemo(() => {
    if (models.length === 0) {
      return settings.context.model_name;
    }

    return (
      models.find((model) => model.name === settings.context.model_name)
        ?.name ?? models[0]?.name
    );
  }, [models, settings.context.model_name]);

  const resolvedContext = useMemo(
    () => ({
      ...settings.context,
      model_name: resolvedModelName,
    }),
    [resolvedModelName, settings.context],
  );

  const threadContext = useMemo(
    () => ({
      model_name: resolvedContext.model_name,
      thinking_enabled:
        resolvedContext.scenario === "research" ||
        (resolvedContext.scenario === "qa" && resolvedContext.tier === "pro"),
      is_plan_mode: resolvedContext.scenario === "research",
      subagent_enabled:
        resolvedContext.scenario === "research" &&
        resolvedContext.tier === "ultra",
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
    if (
      resolvedModelName &&
      settings.context.model_name !== resolvedModelName
    ) {
      setSettings("context", {
        model_name: resolvedModelName,
      });
    }
  }, [resolvedModelName, setSettings, settings.context.model_name]);

  const handleSubmit = useSubmitThread({
    isNewThread,
    threadId,
    thread,
    threadContext,
  });
  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

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
                "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center px-4",
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
            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex size-full justify-center">
                <MessageList
                  className={cn("size-full", !isNewThread && "pt-10")}
                  threadId={threadId}
                  thread={thread}
                  messagesOverride={
                    !thread.isLoading && finalState?.messages
                      ? (finalState.messages as Message[])
                      : undefined
                  }
                  paddingBottom={todoListCollapsed ? 160 : 280}
                />
              </div>
              <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                <div
                  className={cn(
                    "relative w-full",
                    isNewThread && "-translate-y-[calc(50vh-96px)]",
                    isNewThread
                      ? "max-w-(--container-width-sm)"
                      : "max-w-(--container-width-md)",
                  )}
                >
                  <div className="absolute -top-4 right-0 left-0 z-0">
                    <div className="absolute right-0 bottom-0 left-0">
                      <TodoList
                        className="bg-background/5"
                        todos={thread.values.todos ?? []}
                        collapsed={todoListCollapsed}
                        hidden={
                          !thread.values.todos ||
                          thread.values.todos.length === 0
                        }
                        onToggle={() =>
                          setTodoListCollapsed(!todoListCollapsed)
                        }
                      />
                    </div>
                  </div>
                  <InputBox
                    className={cn("bg-background/5 w-full -translate-y-4")}
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
            </main>
          </div>
        </div>
        {artifactPanelOpen && (
          <div
            className="bg-background h-full shrink-0 border-l p-4"
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
      </div>
    </ThreadContext.Provider>
  );
}
