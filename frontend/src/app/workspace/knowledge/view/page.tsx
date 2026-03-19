"use client";

import { ExternalLinkIcon } from "lucide-react";
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
import { buildKnowledgePageImageURL, getKnowledgeParagraphLocation, type KnowledgeParagraphLocation } from "@/core/knowledge/api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeParagraphLocation };

export default function KnowledgeCitationViewPage() {
  const searchParams = useSearchParams();
  const filename = searchParams.get("filename") ?? "";
  const pageNo = searchParams.get("page_no");
  const pdfPageNo = searchParams.get("pdf_page_no");
  const paragraphNo = searchParams.get("paragraph_no");
  const threadId = searchParams.get("thread_id");
  const sourceUrl = normalizeOptionalUrl(searchParams.get("source_url"));
  const originalUrl = normalizeOptionalUrl(searchParams.get("original_url"));
  const backHref = threadId ? `/workspace/chats/${threadId}` : "/workspace/chats";

  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (!filename || (!pageNo && !pdfPageNo && !paragraphNo)) {
      setState({ status: "error", message: "缺少定位参数，无法打开 citation viewer。" });
      return;
    }

    let cancelled = false;
    setState({ status: "loading" });
    getKnowledgeParagraphLocation(filename, {
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
  }, [filename, pageNo, pdfPageNo, paragraphNo]);

  return (
    <div className="min-h-screen px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <Breadcrumb>
              <BreadcrumbList>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link href={backHref}>对话</Link>
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
          <div className="rounded-xl bg-white p-8 text-sm text-muted-foreground shadow-sm">
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
            filename={filename}
          />
        )}
      </div>
    </div>
  );
}

function CitationViewer({
  data,
  filename,
}: {
  data: KnowledgeParagraphLocation;
  filename: string;
}) {
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const pageWidth = data.page_meta?.page_width ?? null;
  const pageHeight = data.page_meta?.page_height ?? null;
  const bbox = data.bbox;
  const imageUrl = useMemo(() => {
    if (!filename || !data.pdf_page_no) {
      return null;
    }
    return buildKnowledgePageImageURL(filename, data.pdf_page_no);
  }, [data.pdf_page_no, filename]);
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

function formatLocationLabel(
  pageNo: number | null,
  paragraphNo: number | null,
): string {
  const pageLabel = pageNo ? `第 ${pageNo} 页` : "页码未知";
  const paragraphLabel = paragraphNo ? `第 ${paragraphNo} 段` : "段落未知";
  return `【${pageLabel} ${paragraphLabel}】`;
}
