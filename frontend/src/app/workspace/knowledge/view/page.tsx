"use client";

import { ExternalLinkIcon, Loader2Icon } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { type CSSProperties, useEffect, useMemo, useState } from "react";

import { KnowledgeStructuredViewer } from "@/components/workspace/artifacts/knowledge-structured-viewer";
import { KNOWLEDGE_SIDE_PANE_WIDTH } from "@/components/workspace/artifacts/knowledge-layout";
import { Button } from "@/components/ui/button";
import {
  buildKnowledgeDocumentUrl,
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeParagraphLocationForDocumentUrl,
  type KnowledgeParagraphLocation,
} from "@/core/knowledge/api";
import { cn } from "@/lib/utils";

const PdfViewer = dynamic(
  () => import("@/components/workspace/artifacts/pdf-viewer").then((module) => module.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex size-full items-center justify-center bg-muted/30 p-4 text-sm text-muted-foreground">
        正在加载 PDF...
      </div>
    ),
  },
);

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
  const explicitOriginalUrl = normalizeOptionalUrl(searchParams.get("original_url"));
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
      documentUrl={documentUrl}
      pageNo={pageNo}
      pdfPageNo={pdfPageNo}
      paragraphNo={paragraphNo}
      explicitOriginalUrl={explicitOriginalUrl}
    />
  );
}

function KnowledgeReaderPage({
  documentUrl,
  filename,
  originFilename,
  originTitle,
  initialPdfPageNo,
  knowledgeSpaceId,
}: {
  documentUrl: string | null;
  filename: string;
  originFilename: string;
  originTitle: string;
  initialPdfPageNo: number;
  knowledgeSpaceId: string | null;
}) {
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number>(
    Math.max(initialPdfPageNo, 1),
  );
  const [pdfPaneOpen, setPdfPaneOpen] = useState(false);
  const supportsPdfPane = useMemo(() => isPdfDocumentUrl(documentUrl), [documentUrl]);
  const layoutStyle = useMemo(
    () =>
      ({
        "--reader-pdf-pane-width": `${KNOWLEDGE_SIDE_PANE_WIDTH}px`,
      }) as CSSProperties,
    [],
  );

  useEffect(() => {
    setCurrentPdfPageNo(Math.max(initialPdfPageNo, 1));
  }, [documentUrl, initialPdfPageNo]);

  useEffect(() => {
    if (!supportsPdfPane) {
      setPdfPaneOpen(false);
    }
  }, [supportsPdfPane]);

  return (
    <div className="h-screen bg-[rgb(247,251,252)] p-4 md:p-6">
      {!documentUrl ? (
        <div className="mx-auto max-w-7xl rounded-xl bg-red-50 p-8 text-sm text-red-700 shadow-sm">
          缺少文档地址，无法打开结构化阅读器。
        </div>
      ) : (
        <div
          className={cn(
            "mx-auto h-full max-w-[1680px] min-h-0",
            pdfPaneOpen && supportsPdfPane
              ? "grid grid-cols-1 gap-4 lg:gap-0 lg:[grid-template-columns:minmax(0,1fr)_var(--reader-pdf-pane-width)]"
              : "block",
          )}
          style={layoutStyle}
        >
          <div className="min-h-0">
            <KnowledgeStructuredViewer
              className="h-full"
              documentUrl={documentUrl}
              initialPdfPageNo={initialPdfPageNo}
              currentPdfPageNo={currentPdfPageNo}
              onCurrentPdfPageNoChange={setCurrentPdfPageNo}
              excerptable
              highlightable={false}
              knowledgeSpaceId={knowledgeSpaceId ?? undefined}
              originFilename={originFilename || filename}
              originTitle={originTitle}
              toolbarExtra={supportsPdfPane ? (
                <Button
                  variant={pdfPaneOpen ? "default" : "outline"}
                  size="sm"
                  className="h-8 rounded-xl"
                  onClick={() => setPdfPaneOpen((open) => !open)}
                >
                  {pdfPaneOpen ? "隐藏原 PDF" : "显示原 PDF"}
                </Button>
              ) : null}
            />
          </div>
          {pdfPaneOpen && supportsPdfPane && (
            <div className="min-h-[420px] overflow-hidden rounded-[28px] border border-[rgba(57,130,152,0.16)] bg-white lg:ml-4">
              <PdfViewer
                url={documentUrl}
                page={currentPdfPageNo - 1}
                className="size-full"
                onPageChange={(page) => setCurrentPdfPageNo(page + 1)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function KnowledgeCitationView({
  documentUrl,
  pageNo,
  pdfPageNo,
  paragraphNo,
  explicitOriginalUrl,
}: {
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
          {originalUrl && (
            <div className="flex justify-end">
              <a
                href={originalUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-white px-3 py-1.5 text-sm text-foreground shadow-sm hover:bg-muted/40"
              >
                打开原文
                <ExternalLinkIcon className="size-4" />
              </a>
            </div>
          )}
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

function isPdfDocumentUrl(url: string | null) {
  if (!url) {
    return false;
  }

  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.pathname.toLowerCase().endsWith(".pdf");
  } catch {
    return url.toLowerCase().endsWith(".pdf");
  }
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
