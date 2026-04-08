"use client";

import { FileSearchIcon, LanguagesIcon, Loader2Icon, ScanTextIcon } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeStructuredPageForDocumentUrl,
  translateKnowledgeParagraphsToChineseForDocumentUrl,
  type KnowledgeStructuredPage,
} from "@/core/knowledge/api";
import { cn } from "@/lib/utils";

type TranslationSourceLanguage = "en" | "ja" | "de";

const LANGUAGE_OPTIONS: Array<{
  value: TranslationSourceLanguage;
  label: string;
  hint: string;
}> = [
  { value: "en", label: "英译中", hint: "英文资料" },
  { value: "ja", label: "日译中", hint: "日文资料" },
  { value: "de", label: "德译中", hint: "德文资料" },
];

export function KnowledgeTranslationWorkspace({
  documentUrl,
  currentPdfPageNo,
  sourceLanguage,
  onSourceLanguageChange,
  onPageDataChange,
}: {
  documentUrl: string;
  currentPdfPageNo: number;
  sourceLanguage: TranslationSourceLanguage;
  onSourceLanguageChange: (value: TranslationSourceLanguage) => void;
  onPageDataChange?: (page: KnowledgeStructuredPage | null) => void;
}) {
  const [pageState, setPageState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; data: KnowledgeStructuredPage }
  >({ status: "loading" });
  const [translationCache, setTranslationCache] = useState<Record<string, Record<string, string>>>({});
  const [translationState, setTranslationState] = useState<
    | { status: "idle" | "loading" }
    | { status: "error"; message: string }
    | { status: "ready" }
  >({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    setPageState({ status: "loading" });

    getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
      pdfPageNo: currentPdfPageNo,
    })
      .then((page) => {
        if (!cancelled) {
          setPageState({ status: "ready", data: page });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setPageState({
            status: "error",
            message: error.message || "结构化文本加载失败",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentPdfPageNo, documentUrl]);

  const pageData = pageState.status === "ready" ? pageState.data : null;

  useEffect(() => {
    onPageDataChange?.(pageData);
  }, [onPageDataChange, pageData]);

  const translationCacheKey = useMemo(() => {
    if (!pageData) {
      return null;
    }
    return [
      pageData.filename,
      pageData.pdf_page_no ?? currentPdfPageNo,
      sourceLanguage,
    ].join(":");
  }, [currentPdfPageNo, pageData, sourceLanguage]);

  const translationMap = translationCacheKey
    ? translationCache[translationCacheKey] ?? null
    : null;

  useEffect(() => {
    if (!pageData || !translationCacheKey || translationMap) {
      return;
    }

    let cancelled = false;
    setTranslationState({ status: "loading" });

    translateKnowledgeParagraphsToChineseForDocumentUrl(
      documentUrl,
      (pageData.paragraphs ?? []).map((paragraph) => ({
        key:
          paragraph.paragraph_id ??
          `${pageData.pdf_page_no ?? currentPdfPageNo}:${paragraph.paragraph_no ?? paragraph.text}`,
        text: paragraph.text,
      })),
      {
        sourceLanguageHint: sourceLanguage,
      },
    )
      .then((translations) => {
        if (cancelled) {
          return;
        }
        setTranslationCache((current) => ({
          ...current,
          [translationCacheKey]: Object.fromEntries(
            translations.map((item) => [item.key, item.translation]),
          ),
        }));
        setTranslationState({ status: "ready" });
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setTranslationState({
            status: "error",
            message: error.message || "翻译失败",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    currentPdfPageNo,
    documentUrl,
    pageData,
    sourceLanguage,
    translationCacheKey,
    translationMap,
  ]);

  const imageUrl = useMemo(() => {
    if (!pageData?.pdf_page_no) {
      return null;
    }
    return buildKnowledgePageImageURLForDocumentUrl(documentUrl, pageData.pdf_page_no);
  }, [documentUrl, pageData?.pdf_page_no]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[rgb(248,250,250)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(57,130,152,0.14)] bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
        {LANGUAGE_OPTIONS.map((option) => (
            <Button
              key={option.value}
              variant={sourceLanguage === option.value ? "default" : "outline"}
              size="sm"
              className="h-8 rounded-xl"
              onClick={() => onSourceLanguageChange(option.value)}
            >
              <LanguagesIcon className="mr-1.5 size-4" />
              {option.label}
            </Button>
          ))}
        </div>
        <div className="text-xs text-slate-500">
          当前页按 {LANGUAGE_OPTIONS.find((item) => item.value === sourceLanguage)?.hint} 翻译
        </div>
      </div>

      {pageState.status === "loading" && (
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
          <Loader2Icon className="mr-2 size-4 animate-spin" />
          正在加载 PDF 页面与 OCR 文本...
        </div>
      )}

      {pageState.status === "error" && (
        <div className="flex flex-1 items-center justify-center px-6 text-sm text-red-600">
          {pageState.message}
        </div>
      )}

      {pageData && (
        <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[1.15fr_1fr_1fr]">
          <ColumnCard
            title="PDF 原文"
            icon={<FileSearchIcon className="size-4" />}
          >
            {imageUrl ? (
              <div className="overflow-auto rounded-2xl bg-[rgb(247,243,236)] p-3">
                <img
                  src={imageUrl}
                  alt={`${pageData.title} PDF 第 ${pageData.pdf_page_no ?? currentPdfPageNo} 页`}
                  className="mx-auto max-w-full rounded-xl bg-white shadow-sm"
                />
              </div>
            ) : (
              <EmptyColumn text="当前页没有可展示的 PDF 画面。" />
            )}
          </ColumnCard>

          <ColumnCard
            title="OCR 文本"
            icon={<ScanTextIcon className="size-4" />}
          >
            {pageData.paragraphs.length > 0 ? (
              <div className="space-y-3">
                {pageData.paragraphs.map((paragraph) => {
                  const paragraphKey =
                    paragraph.paragraph_id ??
                    `${pageData.pdf_page_no ?? currentPdfPageNo}:${paragraph.paragraph_no ?? paragraph.text}`;
                  return (
                    <div
                      key={paragraphKey}
                      className="rounded-2xl border border-slate-200 bg-white p-3"
                    >
                      <div className="mb-2 text-xs font-medium text-slate-500">
                        第 {paragraph.paragraph_no ?? 1} 段
                      </div>
                      <div className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-800">
                        {paragraph.text}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyColumn text="当前页暂无结构化 OCR 内容。" />
            )}
          </ColumnCard>

          <ColumnCard
            title="中文翻译"
            icon={<LanguagesIcon className="size-4" />}
          >
            {translationState.status === "loading" && !translationMap ? (
              <EmptyColumn text="正在翻译当前页..." loading />
            ) : translationState.status === "error" && !translationMap ? (
              <EmptyColumn text={translationState.message} error />
            ) : pageData.paragraphs.length > 0 ? (
              <div className="space-y-3">
                {pageData.paragraphs.map((paragraph) => {
                  const paragraphKey =
                    paragraph.paragraph_id ??
                    `${pageData.pdf_page_no ?? currentPdfPageNo}:${paragraph.paragraph_no ?? paragraph.text}`;
                  return (
                    <div
                      key={`${paragraphKey}-translation`}
                      className={cn(
                        "rounded-2xl border p-3",
                        translationMap?.[paragraphKey]
                          ? "border-emerald-200 bg-emerald-50/50"
                          : "border-slate-200 bg-white",
                      )}
                    >
                      <div className="mb-2 text-xs font-medium text-slate-500">
                        第 {paragraph.paragraph_no ?? 1} 段
                      </div>
                      <div className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-800">
                        {translationMap?.[paragraphKey] ?? "该段翻译暂未返回结果。"}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyColumn text="当前页暂无可翻译文本。" />
            )}
          </ColumnCard>
        </div>
      )}
    </div>
  );
}

function ColumnCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-[24px] border border-[rgba(57,130,152,0.14)] bg-white">
      <div className="flex items-center gap-2 border-b border-[rgba(57,130,152,0.12)] px-4 py-3 text-sm font-medium text-slate-800">
        {icon}
        {title}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
    </section>
  );
}

function EmptyColumn({
  text,
  loading = false,
  error = false,
}: {
  text: string;
  loading?: boolean;
  error?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex min-h-[180px] items-center justify-center rounded-2xl border border-dashed px-6 text-center text-sm",
        error
          ? "border-red-200 bg-red-50 text-red-600"
          : "border-slate-200 bg-slate-50 text-slate-500",
      )}
    >
      {loading && <Loader2Icon className="mr-2 size-4 animate-spin" />}
      {text}
    </div>
  );
}
