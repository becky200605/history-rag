import { getBackendBaseURL } from "@/core/config";

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

export interface KnowledgeFileInfo {
  filename: string;
  size: number;
  artifact_url: string;
  extension?: string;
  modified?: number;
  parse_method?: string;
  parse_status?: string;
  indexable?: boolean;
  preview_filename?: string | null;
  preview_artifact_url?: string | null;
  structured_filename?: string | null;
  structured_artifact_url?: string | null;
  index_target_filename?: string | null;
  index_target_artifact_url?: string | null;
  error?: string | null;
  hints?: Record<string, string>;
  type?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  tags?: string[];
  queue_stage?: string | null;
  queue_position?: number | null;
}

export interface KnowledgeMetadataUpdateInput {
  type?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
}

export interface KnowledgeUploadOptions {
  languageHint?: string;
  layoutHint?: string;
  documentTypeHint?: string;
}

export interface KnowledgeUploadResponse {
  success: boolean;
  files: KnowledgeFileInfo[];
  message: string;
}

export interface KnowledgeListResponse {
  files: KnowledgeFileInfo[];
  count: number;
}

export interface KnowledgeParagraphLocation {
  doc_id?: string | null;
  scope?: "global" | "thread" | "user" | null;
  filename: string;
  title: string;
  page_count?: number | null;
  page_no?: number | null;
  pdf_page_no?: number | null;
  book_page_no?: number | null;
  paragraph_no?: number | null;
  bbox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  page_meta?: {
    page_width?: number;
    page_height?: number;
  } | null;
  text: string;
  source_url?: string | null;
  original_url?: string | null;
}

export interface KnowledgeStructuredParagraph {
  paragraph_id?: string;
  paragraph_no?: number | null;
  paragraph_no_in_doc?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  text: string;
  bbox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
}

export interface KnowledgeStructuredPage {
  doc_id?: string | null;
  scope?: "global" | "thread" | "user" | null;
  filename: string;
  title: string;
  page_count?: number | null;
  page_no?: number | null;
  pdf_page_no?: number | null;
  book_page_no?: number | null;
  page_number_source?: string | null;
  page_meta?: {
    page_width?: number;
    page_height?: number;
  } | null;
  paragraphs: KnowledgeStructuredParagraph[];
  source_url?: string | null;
  original_url?: string | null;
}

export interface KnowledgeTranslationParagraphInput {
  key: string;
  text: string;
}

export interface KnowledgeTranslationParagraphResult {
  key: string;
  translation: string;
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

export type ResolvedKnowledgeDocument =
  | { scope: "global"; filename: string }
  | { scope: "user"; filename: string; basePath: string };

export function resolveKnowledgeDocumentUrl(documentUrl: string): ResolvedKnowledgeDocument | null {
  try {
    const base =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost:2026";
    const url = new URL(documentUrl, base);
    const globalMatch = /\/api\/knowledge\/docs\/([^/]+)$/.exec(url.pathname);
    if (globalMatch) {
      return {
        scope: "global",
        filename: decodeURIComponent(globalMatch[1] ?? ""),
      };
    }
    const userMatch = /(\/api\/secure-knowledge\/users\/me\/knowledge\/docs\/)([^/]+)$/.exec(url.pathname);
    if (userMatch) {
      return {
        scope: "user",
        basePath: userMatch[1] ?? "/api/secure-knowledge/users/me/knowledge/docs/",
        filename: decodeURIComponent(userMatch[2] ?? ""),
      };
    }
    return null;
  } catch {
    return null;
  }
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

export async function uploadKnowledgeFiles(
  files: File[],
  options?: KnowledgeUploadOptions,
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  if (options?.languageHint) {
    formData.append("language_hint", options.languageHint);
  }
  if (options?.layoutHint) {
    formData.append("layout_hint", options.layoutHint);
  }
  if (options?.documentTypeHint) {
    formData.append("document_type_hint", options.documentTypeHint);
  }

  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail ?? "Upload failed");
  }
  return (await response.json()) as KnowledgeUploadResponse;
}

export async function listKnowledgeFiles(): Promise<KnowledgeListResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads/list`);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to list files" }));
    throw new Error(error.detail ?? "Failed to list files");
  }
  return (await response.json()) as KnowledgeListResponse;
}

export async function deleteKnowledgeFile(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete file" }));
    throw new Error(error.detail ?? "Failed to delete file");
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function updateKnowledgeFileMetadata(
  filename: string,
  payload: KnowledgeMetadataUpdateInput,
): Promise<{ success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/metadata`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to update metadata" }));
    throw new Error(error.detail ?? "Failed to update metadata");
  }
  return (await response.json()) as { success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } };
}

export async function getKnowledgeParagraphLocation(
  filename: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
    paragraphNo?: string | number | null;
  },
): Promise<KnowledgeParagraphLocation> {
  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  if (options.paragraphNo) {
    params.set("paragraph_no", String(options.paragraphNo));
  }
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/paragraph-location?${params.toString()}`,
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch paragraph location" }));
    throw new Error(error.detail ?? "Failed to fetch paragraph location");
  }
  return (await response.json()) as KnowledgeParagraphLocation;
}

export async function getKnowledgeStructuredPage(
  filename: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
  },
): Promise<KnowledgeStructuredPage> {
  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/structured-page?${params.toString()}`,
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch structured page" }));
    throw new Error(error.detail ?? "Failed to fetch structured page");
  }
  return (await response.json()) as KnowledgeStructuredPage;
}

export async function getKnowledgeParagraphLocationForDocumentUrl(
  documentUrl: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
    paragraphNo?: string | number | null;
  },
): Promise<KnowledgeParagraphLocation> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  if (options.paragraphNo) {
    params.set("paragraph_no", String(options.paragraphNo));
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;
  const response = await fetch(`${basePath}/paragraph-location?${params.toString()}`);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch paragraph location" }));
    throw new Error(error.detail ?? "Failed to fetch paragraph location");
  }
  return (await response.json()) as KnowledgeParagraphLocation;
}

export async function getKnowledgeStructuredPageForDocumentUrl(
  documentUrl: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
  },
): Promise<KnowledgeStructuredPage> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;
  const response = await fetch(`${basePath}/structured-page?${params.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch structured page" }));
    throw new Error(error.detail ?? "Failed to fetch structured page");
  }
  return (await response.json()) as KnowledgeStructuredPage;
}

export async function translateKnowledgeParagraphsToChineseForDocumentUrl(
  documentUrl: string,
  paragraphs: KnowledgeTranslationParagraphInput[],
): Promise<KnowledgeTranslationParagraphResult[]> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;

  const response = await fetch(`${basePath}/translate-blocks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paragraphs }),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to translate page paragraphs" }));
    throw new Error(error.detail ?? "Failed to translate page paragraphs");
  }

  const payload = (await response.json()) as {
    translations?: Array<{ key?: string | null; translation?: string | null }>;
  };
  return (payload.translations ?? []).map((item) => ({
    key: String(item.key ?? ""),
    translation: String(item.translation ?? ""),
  }));
}

export function buildKnowledgePageImageURL(
  filename: string,
  pdfPageNo: string | number,
): string {
  const params = new URLSearchParams({
    pdf_page_no: String(pdfPageNo),
  });
  return `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/page-image?${params.toString()}`;
}

export function buildKnowledgePageImageURLForDocumentUrl(
  documentUrl: string,
  pdfPageNo: string | number,
): string {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }
  const params = new URLSearchParams({
    pdf_page_no: String(pdfPageNo),
  });
  if (resolved.scope === "global") {
    return `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}/page-image?${params.toString()}`;
  }
  return `${resolved.basePath}${encodeURIComponent(resolved.filename)}/page-image?${params.toString()}`;
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
