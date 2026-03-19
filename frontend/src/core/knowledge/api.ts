import { getBackendBaseURL } from "@/core/config";

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
}

export interface KnowledgeUploadOptions {
  languageHint?: string;
  layoutHint?: string;
  documentTypeHint?: string;
  bookPageStartPdfPage?: string;
  bookPageStartValue?: string;
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
  filename: string;
  title: string;
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
  if (options?.bookPageStartPdfPage) {
    formData.append("book_page_start_pdf_page", options.bookPageStartPdfPage);
  }
  if (options?.bookPageStartValue) {
    formData.append("book_page_start_value", options.bookPageStartValue);
  }

  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail ?? "Upload failed");
  }
  return response.json();
}

export async function listKnowledgeFiles(): Promise<KnowledgeListResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads/list`);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to list files" }));
    throw new Error(error.detail ?? "Failed to list files");
  }
  return response.json();
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
  return response.json();
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
  return response.json();
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
