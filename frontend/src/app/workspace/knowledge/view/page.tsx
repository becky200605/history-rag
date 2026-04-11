"use client";

import { ExternalLinkIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { KnowledgeStructuredViewer } from "@/components/workspace/artifacts/knowledge-structured-viewer";
import {
  buildKnowledgeDocumentUrl,
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeParagraphLocationForDocumentUrl,
  type KnowledgeParagraphLocation,
} from "@/core/knowledge/api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeParagraphLocation };

export default function KnowledgeViewPage() {
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode");
  const filename = searchParams.get("filename") ?? "";
  const scope = searchParams.get("scope");
  const rawDocumentUrl = normalizeOptionalUrl(searchParams.get("document_url"));
  const pageNo = searchParams.get("page_no");
  const pdfPageNo = searchParams.get("pdf_page_no");
  const paragraphNo = searchParams.get("paragraph_no");
  const threadId = searchParams.get("thread_id");
  const explicitOriginalUrl = normalizeOptionalUrl(searchParams.get("original_url"));
  const backHref = normalizeOptionalUrl(searchParams.get("back_href"))
    ?? (threadId ? `/workspace/chats/${threadId}` : "/workspace/chats");
  const backLabel = searchParams.get("back_label") ?? (threadId ? "对话" : "对话");
  const originTitle = searchParams.get("origin_title") ?? (filename || "未命名资料");
  const originFilename = searchParams.get("origin_filename") ?? (filename || "未知文件");
  const knowledgeSpaceId = searchParams.get("knowledge_space_id");
  const documentUrl = useMemo(() => {
    if (rawDocumentUrl) {
      return rawDocumentUrl;
    }
    if (!filename) {
      return null;
    }
    return buildKnowledgeDocumentUrl(scope === "user" ? "user" : "global", filename);
  }, [filename, rawDocumentUrl, scope]);

  if (mode === "reader") {
    return (
      <KnowledgeReaderPage
        backHref={backHref}
        backLabel={backLabel}
        documentUrl={documentUrl}
        filename={filename}
        originFilename={originFilename}
        originTitle={originTitle}
        initialPdfPageNo={parsePositiveInteger(pdfPageNo) ?? 1}
        knowledgeSpaceId={knowledgeSpaceId}
      />
    );
  }

  return (
    <KnowledgeCitationView
      backHref={backHref}
      backLabel={backLabel}
      documentUrl={documentUrl}
      pageNo={pageNo}
      pdfPageNo={pdfPageNo}
      paragraphNo={paragraphNo}
      explicitOriginalUrl={explicitOriginalUrl}
    />
  );
}

function KnowledgeReaderPage({
  backHref,
  backLabel,
  documentUrl,
  filename,
  originFilename,
  originTitle,
  initialPdfPageNo,
  knowledgeSpaceId,
}: {
  backHref: string;
  backLabel: string;
  documentUrl: string | null;
  filename: string;
  originFilename: string;
  originTitle: string;
  initialPdfPageNo: number;
  knowledgeSpaceId: string | null;
}) {
  return (
    <div className="min-h-screen bg-[rgb(247,251,252)] px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <div className="space-y-3">
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link href={backHref}>{backLabel}</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>结构化阅读</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              {originTitle}
            </h1>
            <div className="text-sm text-slate-500">
              {originFilename || filename}
            </div>
          </div>
        </div>

        {!documentUrl ? (
          <div className="rounded-xl bg-red-50 p-8 text-sm text-red-700 shadow-sm">
            缺少文档地址，无法打开结构化阅读器。
          </div>
        ) : (
          <KnowledgeStructuredViewer
            className="min-h-[calc(100vh-190px)]"
            documentUrl={documentUrl}
            initialPdfPageNo={initialPdfPageNo}
            excerptable
            highlightable={false}
            knowledgeSpaceId={knowledgeSpaceId ?? undefined}
            originFilename={originFilename || filename}
            originTitle={originTitle}
          />
        )}
      </div>
    </div>
  );
}

function KnowledgeCitationView({
  backHref,
  backLabel,
  documentUrl,
  pageNo,
  pdfPageNo,
  paragraphNo,
  explicitOriginalUrl,
}: {
  backHref: string;
  backLabel: string;
  documentUrl: string | null;
  pageNo: string | null;
  pdfPageNo: string | null;
  paragraphNo: string | null;
  explicitOriginalUrl: string | null;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (!documentUrl || (!pageNo && !pdfPageNo && !paragraphNo)) {
      setState({ status: "error", message: "缺少定位参数，无法打开 citation viewer。" });
      return;
    }

    let cancelled = false;
    setState({ status: "loading" });
    getKnowledgeParagraphLocationForDocumentUrl(documentUrl, {
      pageNo,
      pdfPageNo,
      paragraphNo,
    })
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({ status: "error", message: error.message || "定位信息加载失败" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, pageNo, pdfPageNo, paragraphNo]);

  const originalUrl = explicitOriginalUrl
    ?? (state.status === "ready" ? state.data.original_url ?? null : null);

  return (
    <div className="min-h-screen px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <Breadcrumb>
              <BreadcrumbList>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link href={backHref}>{backLabel}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator />
                <BreadcrumbItem>
                  <BreadcrumbPage>citation 定位查看</BreadcrumbPage>
                </BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
            {originalUrl && (
              <a
                href={originalUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-white px-3 py-1.5 text-sm text-foreground shadow-sm hover:bg-muted/40"
              >
                打开原文
                <ExternalLinkIcon className="size-4" />
              </a>
            )}
          </div>

          {state.status === "ready" && (
            <div className="space-y-1 text-center">
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                {state.data.title}
              </h1>
              <div className="text-sm text-muted-foreground">
                {formatLocationLabel(
                  state.data.page_no ?? null,
                  state.data.paragraph_no ?? null,
                )}
              </div>
            </div>
          )}
        </div>

        {state.status === "loading" && (
          <div className="flex items-center gap-2 rounded-xl bg-white p-8 text-sm text-muted-foreground shadow-sm">
            <Loader2Icon className="size-4 animate-spin" />
            正在加载页码与段落定位信息...
          </div>
        )}

        {state.status === "error" && (
          <div className="rounded-xl bg-red-50 p-8 text-sm text-red-700 shadow-sm">
            {state.message}
          </div>
        )}

        {state.status === "ready" && (
          <CitationViewer
            data={state.data}
            documentUrl={documentUrl}
          />
        )}
      </div>
    </div>
  );
}

function CitationViewer({
  data,
  documentUrl,
}: {
  data: KnowledgeParagraphLocation;
  documentUrl: string | null;
}) {
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const pageWidth = data.page_meta?.page_width ?? null;
  const pageHeight = data.page_meta?.page_height ?? null;
  const bbox = data.bbox;
  const imageUrl = useMemo(() => {
    if (!documentUrl || !data.pdf_page_no) {
      return null;
    }
    return buildKnowledgePageImageURLForDocumentUrl(documentUrl, data.pdf_page_no);
  }, [data.pdf_page_no, documentUrl]);
  const overlayStyle =
    bbox && pageWidth && pageHeight && imageSize
      ? {
          left: `${(bbox.x / pageWidth) * imageSize.width}px`,
          top: `${(bbox.y / pageHeight) * imageSize.height}px`,
          width: `${(bbox.width / pageWidth) * imageSize.width}px`,
          height: `${(bbox.height / pageHeight) * imageSize.height}px`,
        }
      : null;

  return (
    <div>
      {imageUrl ? (
        <div className="overflow-auto">
          <div className="relative flex justify-center">
            <img
              src={imageUrl}
              alt={`${data.title} PDF page ${data.pdf_page_no ?? ""}`}
              className="max-w-full bg-white"
              onLoad={(event) => {
                const img = event.currentTarget;
                setImageSize({ width: img.clientWidth, height: img.clientHeight });
              }}
            />
            {overlayStyle && (
              <div
                className="pointer-events-none absolute rounded-md border-2 border-emerald-500/90 bg-emerald-300/12"
                style={overlayStyle}
              />
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-lg bg-muted/40 p-6 text-sm text-muted-foreground">
          当前缺少 PDF 页码，无法渲染页面截图。
        </div>
      )}
    </div>
  );
}

function normalizeOptionalUrl(url: string | null): string | null {
  if (!url) {
    return null;
  }
  try {
    return decodeURI(url);
  } catch {
    return url;
  }
}

function parsePositiveInteger(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function formatLocationLabel(pageNo: number | null, paragraphNo: number | null) {
  const parts: string[] = [];
  if (pageNo) {
    parts.push(`第 ${pageNo} 页`);
  }
  if (paragraphNo) {
    parts.push(`第 ${paragraphNo} 段`);
  }
  return parts.join(" · ") || "已定位";
}
