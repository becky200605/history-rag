import type { HumanMessage } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream, type UseStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { SelectedMaterial } from "@/core/knowledge/selection";
import type {
  ThreadDisplayContextSnapshot,
} from "@/core/threads/utils";
import { env } from "@/env";
import { authClient } from "@/server/better-auth/client";

import { getAPIClient } from "../api";
import { useUpdateSubtask } from "../tasks/context";
import { buildThreadDisplayMetadata } from "../threads/utils";
import type { Todo } from "../todos";
import { uploadFiles } from "../uploads";

import type {
  AgentThread,
  AgentThreadContext,
  AgentThreadState,
} from "./types";

export function useThreadStream({
  threadId,
  isNewThread,
  onCreated,
  onFinish,
  onCustomEvent,
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  onCreated?: (run: { run_id: string; thread_id: string }) => void;
  onFinish?: (state: AgentThreadState) => void;
  onCustomEvent?: (event: unknown) => void;
}) {
  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();
  const thread = useStream<AgentThreadState>({
    client: getAPIClient(),
    assistantId: "lead_agent",
    threadId: isNewThread ? undefined : threadId,
    reconnectOnMount: true,
    fetchStateHistory: true,
    onCreated(run) {
      onCreated?.(run);
    },
    onCustomEvent(event: unknown, options) {
      console.info(event);
      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event
      ) {
        const e = event as
          | {
              type: "task_started";
              task_id: string;
              description?: string;
            }
          | {
              type: "task_running";
              task_id: string;
              message: AIMessage;
            }
          | {
              type: "task_completed";
              task_id: string;
              result?: string;
              summary?: string;
              findings?: string[];
              citations?: string[];
              open_questions?: string[];
              execution_time_seconds?: number;
            }
          | {
              type: "task_failed" | "task_timed_out";
              task_id: string;
              error?: string;
              execution_time_seconds?: number;
            }
          | {
              type: "todo_board_updated";
              todos: Todo[];
            };

        if (e.type === "todo_board_updated") {
          options.mutate({
            todos: e.todos,
          });
        }

        if (e.type === "task_started") {
          updateSubtask({
            id: e.task_id,
            status: "in_progress",
            description: e.description ?? e.task_id,
          });
        } else if (e.type === "task_running") {
          updateSubtask({
            id: e.task_id,
            status: "in_progress",
            latestMessage: e.message,
            messages: [e.message],
          });
        } else if (e.type === "task_completed") {
          updateSubtask({
            id: e.task_id,
            status: "completed",
            result: e.result,
            summary: e.summary,
            findings: e.findings,
            citations: e.citations,
            openQuestions: e.open_questions,
            executionTimeSeconds: e.execution_time_seconds,
          });
        } else if (e.type === "task_failed" || e.type === "task_timed_out") {
          updateSubtask({
            id: e.task_id,
            status: "failed",
            error: e.error,
            executionTimeSeconds: e.execution_time_seconds,
          });
        }
      }
      onCustomEvent?.(event);
    },
    onFinish(state) {
      onFinish?.(state.values);
      // void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (!oldData) {
            return oldData;
          }
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title: state.values.title,
                },
              };
            }
            return t;
          });
        },
      );
    },
  });
  return thread;
}

export function useSubmitThread({
  threadId,
  thread,
  threadContext,
  displayContext,
  isNewThread,
  afterSubmit,
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  thread: UseStream<AgentThreadState>;
  threadContext: Omit<AgentThreadContext, "thread_id">;
  displayContext?: ThreadDisplayContextSnapshot;
  afterSubmit?: () => void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  const { data: session } = authClient.useSession();

  const buildEffectiveSelection = useCallback(
    (selectedMaterials?: SelectedMaterial[]) => {
      if (selectedMaterials && selectedMaterials.length > 0) {
        const scopes = Array.from(
          new Set(
            selectedMaterials
              .map((item) => item.scope)
              .filter(
                (scope): scope is "global" | "thread" | "user" =>
                  scope === "global" || scope === "thread" || scope === "user",
              ),
          ),
        );

        return {
          selected_doc_ids: selectedMaterials.map((item) => item.doc_id),
          selected_sources_scope: scopes,
          selected_materials: selectedMaterials,
        };
      }

      return {
        selected_doc_ids: threadContext.selected_doc_ids,
        selected_sources_scope: threadContext.selected_sources_scope,
        selected_materials: threadContext.selected_materials,
      };
    },
    [
      threadContext.selected_doc_ids,
      threadContext.selected_materials,
      threadContext.selected_sources_scope,
    ],
  );

  const callback = useCallback(
    async (message: PromptInputMessage) => {
      const text = message.text.trim();
      const userId = session?.user.id;
      const effectiveSelection = buildEffectiveSelection(
        message.selectedMaterials,
      );

      if (
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
        (!userId || !threadId)
      ) {
        throw new Error("Missing authenticated user or thread ID.");
      }

      const threadMetadata =
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && userId
          ? {
              user_id: userId,
              ...buildThreadDisplayMetadata(displayContext ?? {}),
            }
          : undefined;

      // Upload files first if any
      if (message.files && message.files.length > 0) {
        try {
          // Convert FileUIPart to File objects by fetching blob URLs
          const filePromises = message.files.map(async (fileUIPart) => {
            if (fileUIPart.url && fileUIPart.filename) {
              try {
                // Fetch the blob URL to get the file data
                const response = await fetch(fileUIPart.url);
                const blob = await response.blob();

                // Create a File object from the blob
                return new File([blob], fileUIPart.filename, {
                  type: fileUIPart.mediaType || blob.type,
                });
              } catch (error) {
                console.error(
                  `Failed to fetch file ${fileUIPart.filename}:`,
                  error,
                );
                return null;
              }
            }
            return null;
          });

          const files = (await Promise.all(filePromises)).filter(
            (file): file is File => file !== null,
          );

          if (files.length > 0 && threadId) {
            await uploadFiles(threadId, files);
          }
        } catch (error) {
          console.error("Failed to upload files:", error);
          // Continue with message submission even if upload fails
          // You might want to show an error toast here
        }
      }

      if (
        !isNewThread &&
        threadId &&
        threadMetadata &&
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true"
      ) {
        await apiClient.threads.update(threadId, {
          metadata: threadMetadata,
        });
      }

      await thread.submit(
        {
          messages: [
            {
              type: "human",
              content: [
                {
                  type: "text",
                  text,
                },
              ],
            },
          ] as HumanMessage[],
        },
        {
          threadId: isNewThread ? threadId! : undefined,
          metadata: threadMetadata,
          streamSubgraphs: true,
          streamResumable: true,
          streamMode: ["values", "messages-tuple", "custom"],
          config: {
            recursion_limit: 1000,
          },
          context: {
            ...threadContext,
            thread_id: threadId,
            ...effectiveSelection,
            ...(userId ? { user_id: userId } : {}),
          },
        },
      );
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      await afterSubmit?.();
    },
    [
      thread,
      isNewThread,
      threadId,
      threadContext,
      displayContext,
      apiClient,
      queryClient,
      afterSubmit,
      buildEffectiveSelection,
      session?.user.id,
    ],
  );
  return callback;
}

export function useThreads(
  params: Parameters<ThreadsClient["search"]>[0] = {
    limit: 50,
    sortBy: "updated_at",
    sortOrder: "desc",
  },
) {
  const apiClient = getAPIClient();
  const { data: session, isPending } = authClient.useSession();
  const userId = session?.user.id;
  const shouldUseMetadataFilter =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";

  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params, userId],
    enabled:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
      (!!userId && !isPending),
    queryFn: async () => {
      const response = await apiClient.threads.search<AgentThreadState>({
        ...params,
        metadata:
          shouldUseMetadataFilter && userId
            ? {
                user_id: userId,
              }
            : params.metadata,
      });
      return response as AgentThread[];
    },
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      await apiClient.threads.delete(threadId);
    },
    onSuccess(_, { threadId }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (!oldData) {
            return oldData;
          }
          return oldData.filter((t) => t.thread_id !== threadId);
        },
      );
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await apiClient.threads.updateState(threadId, {
        values: { title },
      });
    },
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (!oldData) {
            return oldData;
          }
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
    },
  });
}
