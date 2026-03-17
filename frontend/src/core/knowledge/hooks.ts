import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import {
  loadKnowledgeStatus,
  triggerReindex,
  uploadKnowledgeDocument,
  type KnowledgeBaseStatus,
  type ReindexResponse,
  type UploadKnowledgeDocumentResponse,
  listKnowledgeDocuments,
  deleteKnowledgeDocument,
  type KnowledgeDocumentListResponse,
} from "./api";
import {
  uploadLargeFile,
  shouldUseChunkedUpload,
  type ChunkedUploadResult,
} from "./chunked-upload";

export function useKnowledgeStatus() {
  const { data, isLoading, error } = useQuery<KnowledgeBaseStatus>({
    queryKey: ["knowledgeStatus"],
    queryFn: () => loadKnowledgeStatus(),
  });
  return { status: data ?? null, isLoading, error };
}

export function useReindexKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation<ReindexResponse, Error, void>({
    mutationFn: async () => triggerReindex(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledgeStatus"] });
    },
  });
}

export function useUploadKnowledgeDocument() {
  const queryClient = useQueryClient();
  return useMutation<UploadKnowledgeDocumentResponse, Error, { file: File; reindex?: boolean }>({
    mutationFn: async ({ file, reindex }) =>
      uploadKnowledgeDocument(file, { reindex }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledgeStatus"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledgeDocs"] });
    },
  });
}

export function useKnowledgeDocuments() {
  const { data, isLoading, error } = useQuery<KnowledgeDocumentListResponse>({
    queryKey: ["knowledgeDocs"],
    queryFn: () => listKnowledgeDocuments(),
  });
  return { docs: data?.docs ?? [], isLoading, error };
}

export function useDeleteKnowledgeDocument() {
  const queryClient = useQueryClient();
  return useMutation<{ success: boolean; message: string }, Error, string>({
    mutationFn: async (filename: string) =>
      deleteKnowledgeDocument(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledgeDocs"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledgeStatus"] });
    },
  });
}

export interface UploadProgress {
  progress: number;
  uploadedBytes: number;
  totalBytes: number;
}

/**
 * Hook for uploading knowledge documents with automatic chunked upload for large files.
 * 
 * Automatically uses chunked upload for files > 10MB.
 * Provides progress tracking for large file uploads.
 */
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
          // Use chunked upload for large files
          abortControllerRef.current = new AbortController();
          
          result = await uploadLargeFile(file, {
            reindex: options?.reindex,
            signal: abortControllerRef.current.signal,
            onProgress: (progress, uploadedBytes, totalBytes) => {
              setUploadProgress({ progress, uploadedBytes, totalBytes });
            },
          });
        } else {
          // Use regular upload for small files
          result = await uploadKnowledgeDocument(file, { reindex: options?.reindex });
        }

        // Invalidate queries to refresh data
        void queryClient.invalidateQueries({ queryKey: ["knowledgeStatus"] });
        void queryClient.invalidateQueries({ queryKey: ["knowledgeDocs"] });

        return result;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
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

