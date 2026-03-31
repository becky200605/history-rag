import type { HumanMessage } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream, type UseStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { env } from "@/env";
import { authClient } from "@/server/better-auth/client";

import { getAPIClient } from "../api";
import { useUpdateSubtask } from "../tasks/context";
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
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  onCreated?: (run: { run_id: string; thread_id: string }) => void;
  onFinish?: (state: AgentThreadState) => void;
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
    onCustomEvent(event: unknown) {
      console.info(event);
      if (
        typeof event === "object" &&
        event !== null &&
        "type" in event &&
        event.type === "task_running"
      ) {
        const e = event as {
          type: "task_running";
          task_id: string;
          message: AIMessage;
        };
        updateSubtask({ id: e.task_id, latestMessage: e.message });
      }
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
  isNewThread,
  afterSubmit,
}: {
  isNewThread: boolean;
  threadId: string | null | undefined;
  thread: UseStream<AgentThreadState>;
  threadContext: Omit<AgentThreadContext, "thread_id">;
  afterSubmit?: () => void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const { data: session } = authClient.useSession();
  const callback = useCallback(
    async (message: PromptInputMessage) => {
      const text = message.text.trim();
      const userId = session?.user.id;

      if (
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
        (!userId || !threadId)
      ) {
        throw new Error("Missing authenticated user or thread ID.");
      }

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
          metadata:
            env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && userId
              ? {
                  user_id: userId,
                }
              : undefined,
          streamSubgraphs: true,
          streamResumable: true,
          streamMode: ["values", "messages-tuple", "custom"],
          config: {
            recursion_limit: 1000,
          },
          context: {
            ...threadContext,
            thread_id: threadId,
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
      queryClient,
      afterSubmit,
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
  const shouldUseMetadataFilter = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";

  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params, userId],
    enabled: env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || (!!userId && !isPending),
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
