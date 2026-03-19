import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteKnowledgeFile,
  listKnowledgeFiles,
  type KnowledgeUploadOptions,
  type KnowledgeUploadResponse,
  uploadKnowledgeFiles,
} from "./api";

const KNOWLEDGE_FILES_QUERY_KEY = ["knowledge", "uploads"];

export function useKnowledgeFiles() {
  return useQuery({
    queryKey: KNOWLEDGE_FILES_QUERY_KEY,
    queryFn: listKnowledgeFiles,
    refetchInterval: (query) => {
      const files = query.state.data?.files ?? [];
      const hasActiveJobs = files.some((file) =>
        ["queued", "parsing", "indexing"].includes(file.parse_status ?? ""),
      );
      return hasActiveJobs ? 2000 : false;
    },
  });
}

export function useUploadKnowledgeFiles() {
  const queryClient = useQueryClient();
  return useMutation<
    KnowledgeUploadResponse,
    Error,
    { files: File[]; options?: KnowledgeUploadOptions }
  >({
    mutationFn: ({ files, options }) => uploadKnowledgeFiles(files, options),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
    },
  });
}

export function useDeleteKnowledgeFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => deleteKnowledgeFile(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
    },
  });
}
