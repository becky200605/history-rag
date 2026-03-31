import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import {
  deleteKnowledgeDocument,
  deleteKnowledgeFile,
  listKnowledgeDocuments,
  listKnowledgeFiles,
  loadKnowledgeStatus,
  retryKnowledgeFileIndexing,
  triggerReindex,
  updateKnowledgeFileMetadata,
  type KnowledgeBaseStatus,
  type KnowledgeDocumentListResponse,
  type KnowledgeMetadataUpdateInput,
  type KnowledgeUploadOptions,
  type KnowledgeUploadResponse,
  type ReindexResponse,
  type UploadKnowledgeDocumentResponse,
  uploadKnowledgeDocument,
  uploadKnowledgeFiles,
} from "./api";
import {
  shouldUseChunkedUpload,
  uploadLargeFile,
  type ChunkedUploadResult,
} from "./chunked-upload";

const KNOWLEDGE_FILES_QUERY_KEY = ["knowledge", "uploads"];
const KNOWLEDGE_STATUS_QUERY_KEY = ["knowledgeStatus"];
const KNOWLEDGE_DOCS_QUERY_KEY = ["knowledgeDocs"];
const ACTIVE_KNOWLEDGE_JOB_STATUSES = [
  "queued",
  "queued_ocr",
  "parsing",
  "queued_embedding",
  "indexing",
];

export function useKnowledgeFiles() {
  return useQuery({
    queryKey: KNOWLEDGE_FILES_QUERY_KEY,
    queryFn: listKnowledgeFiles,
    refetchInterval: (query) => {
      const files = query.state.data?.files ?? [];
      const hasActiveJobs = files.some((file) =>
        ACTIVE_KNOWLEDGE_JOB_STATUSES.includes(file.parse_status ?? ""),
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
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
    },
  });
}

export function useDeleteKnowledgeFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => deleteKnowledgeFile(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
    },
  });
}

export function useRetryKnowledgeFileIndexing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => retryKnowledgeFileIndexing(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
    },
  });
}

export function useUpdateKnowledgeFileMetadata() {
  const queryClient = useQueryClient();
  return useMutation<
    { success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } },
    Error,
    { filename: string; payload: KnowledgeMetadataUpdateInput }
  >({
    mutationFn: ({ filename, payload }) =>
      updateKnowledgeFileMetadata(filename, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
    },
  });
}

export function useKnowledgeStatus() {
  const { data, isLoading, error } = useQuery<KnowledgeBaseStatus>({
    queryKey: KNOWLEDGE_STATUS_QUERY_KEY,
    queryFn: () => loadKnowledgeStatus(),
  });
  return { status: data ?? null, isLoading, error };
}

export function useReindexKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation<ReindexResponse, Error, void>({
    mutationFn: async () => triggerReindex(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
    },
  });
}

export function useUploadKnowledgeDocument() {
  const queryClient = useQueryClient();
  return useMutation<
    UploadKnowledgeDocumentResponse,
    Error,
    { file: File; reindex?: boolean }
  >({
    mutationFn: async ({ file, reindex }) => uploadKnowledgeDocument(file, { reindex }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
    },
  });
}

export function useKnowledgeDocuments() {
  const { data, isLoading, error } = useQuery<KnowledgeDocumentListResponse>({
    queryKey: KNOWLEDGE_DOCS_QUERY_KEY,
    queryFn: () => listKnowledgeDocuments(),
  });
  return { docs: data?.docs ?? [], isLoading, error };
}

export function useDeleteKnowledgeDocument() {
  const queryClient = useQueryClient();
  return useMutation<{ success: boolean; message: string }, Error, string>({
    mutationFn: async (filename: string) => deleteKnowledgeDocument(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });
    },
  });
}

export interface UploadProgress {
  progress: number;
  uploadedBytes: number;
  totalBytes: number;
}

export function useSmartUploadKnowledgeDocument() {
  const queryClient = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const upload = useCallback(
    async (file: File, options?: { reindex?: boolean }) => {
      setIsUploading(true);
      setError(null);
      setUploadProgress(null);

      try {
        let result: UploadKnowledgeDocumentResponse | ChunkedUploadResult;

        if (shouldUseChunkedUpload(file)) {
          abortControllerRef.current = new AbortController();
          result = await uploadLargeFile(file, {
            reindex: options?.reindex,
            signal: abortControllerRef.current.signal,
            onProgress: (progress, uploadedBytes, totalBytes) => {
              setUploadProgress({ progress, uploadedBytes, totalBytes });
            },
          });
        } else {
          result = await uploadKnowledgeDocument(file, { reindex: options?.reindex });
        }

        void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_STATUS_QUERY_KEY });
        void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_DOCS_QUERY_KEY });
        void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_FILES_QUERY_KEY });

        return result;
      } catch (err) {
        const uploadError = err instanceof Error ? err : new Error(String(err));
        setError(uploadError);
        throw uploadError;
      } finally {
        setIsUploading(false);
        abortControllerRef.current = null;
      }
    },
    [queryClient],
  );

  const cancel = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setUploadProgress(null);
    setError(null);
  }, []);

  return {
    upload,
    cancel,
    reset,
    isUploading,
    uploadProgress,
    error,
  };
}

export { shouldUseChunkedUpload };
