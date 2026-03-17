import { getBackendBaseURL } from "../config";

export interface KnowledgeBaseStatus {
  enabled: boolean;
  doc_count: number;
  collection_name: string;
  docs_path: string;
}

export interface ReindexResponse {
  status: string;
  message: string;
}

export interface UploadKnowledgeDocumentResponse {
  status: string;
  message: string;
  filename: string;
  markdown_filename?: string | null;
}

export interface KnowledgeDocumentInfo {
  filename: string;
  size: number;
  modified: number;
  extension: string;
}

export interface KnowledgeDocumentListResponse {
  docs: KnowledgeDocumentInfo[];
}

export async function loadKnowledgeStatus(): Promise<KnowledgeBaseStatus> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/status`);
  if (!res.ok) {
    throw new Error("Failed to load knowledge base status");
  }
  return (await res.json()) as KnowledgeBaseStatus;
}

export async function triggerReindex(): Promise<ReindexResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/reindex`, {
    method: "POST",
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to trigger reindex");
  }
  return (await res.json()) as ReindexResponse;
}

export async function uploadKnowledgeDocument(
  file: File,
  options?: { reindex?: boolean },
): Promise<UploadKnowledgeDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (options?.reindex) {
    params.set("reindex", "true");
  }

  const query = params.toString();
  const url =
    `${getBackendBaseURL()}/api/knowledge/docs/upload` +
    (query ? `?${query}` : "");

  const res = await fetch(url, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to upload knowledge document");
  }

  return (await res.json()) as UploadKnowledgeDocumentResponse;
}

export async function listKnowledgeDocuments(): Promise<KnowledgeDocumentListResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/docs`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to list knowledge documents");
  }
  return (await res.json()) as KnowledgeDocumentListResponse;
}

export async function deleteKnowledgeDocument(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to delete knowledge document");
  }
  return (await res.json()) as { success: boolean; message: string };
}


