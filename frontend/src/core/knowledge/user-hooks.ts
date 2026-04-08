import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createUserKnowledgeSpace,
  createUserDerivedKnowledge,
  deleteUserKnowledgeRecord,
  getUserKnowledgeRecordContent,
  importGlobalKnowledgeToPersonal,
  listUserKnowledgeSpaces,
  listUserKnowledgeRecords,
  type CreateUserDerivedKnowledgeInput,
  type UserKnowledgeRecordContentResponse,
  type UserKnowledgeListResponse,
  type UserKnowledgeSpace,
  type UserKnowledgeUploadResponse,
  updateUserKnowledgeRecordContent,
  uploadUserKnowledgeFiles,
} from "./user-api";

const USER_KNOWLEDGE_QUERY_KEY = ["user-knowledge", "records"];
const USER_KNOWLEDGE_SPACES_QUERY_KEY = ["user-knowledge", "spaces"];
const USER_KNOWLEDGE_CONTENT_QUERY_KEY = ["user-knowledge", "content"];
const ACTIVE_USER_KNOWLEDGE_JOB_STATUSES = [
  "queued",
  "queued_ocr",
  "parsing",
  "queued_embedding",
  "indexing",
  "parsed",
];

export function useUserKnowledgeRecords(knowledgeSpaceId?: string | null) {
  return useQuery<UserKnowledgeListResponse>({
    queryKey: [...USER_KNOWLEDGE_QUERY_KEY, knowledgeSpaceId ?? "all"],
    queryFn: () => listUserKnowledgeRecords(knowledgeSpaceId),
    refetchInterval: (query) => {
      const records = query.state.data?.records ?? [];
      const hasActiveJobs = records.some((record) =>
        ACTIVE_USER_KNOWLEDGE_JOB_STATUSES.includes(record.parse_status ?? ""),
      );
      return hasActiveJobs ? 2000 : false;
    },
  });
}

export function useUserKnowledgeSpaces() {
  return useQuery<{ spaces: UserKnowledgeSpace[] }>({
    queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY,
    queryFn: listUserKnowledgeSpaces,
  });
}

export function useUploadUserKnowledgeFiles() {
  const queryClient = useQueryClient();
  return useMutation<
    UserKnowledgeUploadResponse,
    Error,
    {
      files: File[];
      options?: {
        languageHint?: string;
        layoutHint?: string;
        documentTypeHint?: string;
        knowledgeSpaceId?: string | null;
      };
    }
  >({
    mutationFn: ({ files, options }) => uploadUserKnowledgeFiles(files, options),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
    },
  });
}

export function useImportGlobalKnowledgeToPersonal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, knowledgeSpaceId }: { filename: string; knowledgeSpaceId?: string | null }) =>
      importGlobalKnowledgeToPersonal(filename, knowledgeSpaceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
    },
  });
}

export function useCreateUserKnowledgeSpace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) =>
      createUserKnowledgeSpace(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
    },
  });
}

export function useCreateUserDerivedKnowledge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateUserDerivedKnowledgeInput) =>
      createUserDerivedKnowledge(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
    },
  });
}

export function useDeleteUserKnowledgeRecord() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (recordId: string) => deleteUserKnowledgeRecord(recordId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
    },
  });
}

export function useUserKnowledgeRecordContent(recordId: string | null) {
  return useQuery<UserKnowledgeRecordContentResponse>({
    queryKey: [...USER_KNOWLEDGE_CONTENT_QUERY_KEY, recordId],
    queryFn: () => getUserKnowledgeRecordContent(recordId!),
    enabled: Boolean(recordId),
  });
}

export function useUpdateUserKnowledgeRecordContent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { recordId: string; title: string; content: string }) =>
      updateUserKnowledgeRecordContent(payload.recordId, {
        title: payload.title,
        content: payload.content,
      }),
    onSuccess: (data, variables) => {
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USER_KNOWLEDGE_SPACES_QUERY_KEY });
      queryClient.setQueryData(
        [...USER_KNOWLEDGE_CONTENT_QUERY_KEY, variables.recordId],
        data,
      );
    },
  });
}
