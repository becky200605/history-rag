"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LanguagesIcon,
  ScrollTextIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  KnowledgeSidePane,
  type KnowledgeSidePaneMode,
} from "./knowledge-side-pane";
import { KnowledgeTranslationWorkspace } from "./knowledge-translation-workspace";

export function KnowledgeStructuredViewer({
  className,
  documentUrl,
  initialPdfPageNo = 1,
  interactive = false,
  highlightable,
  excerptable,
  knowledgeSpaceId,
  originFilename,
  originTitle,
}: {
  className?: string;
  documentUrl: string;
  initialPdfPageNo?: number;
  interactive?: boolean;
  highlightable?: boolean;
  excerptable?: boolean;
  knowledgeSpaceId?: string;
  originFilename: string;
  originTitle: string;
}) {
  const [mode, setMode] = useState<KnowledgeSidePaneMode>("compare");
  const [translationSourceLanguage, setTranslationSourceLanguage] = useState<
    "en" | "ja" | "de"
  >("en");
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number>(
    Math.max(initialPdfPageNo, 1),
  );
  const [pageInputValue, setPageInputValue] = useState("");
  const [pageCount, setPageCount] = useState<number | null>(null);

  useEffect(() => {
    setCurrentPdfPageNo(Math.max(initialPdfPageNo, 1));
    setPageInputValue("");
    setPageCount(null);
  }, [documentUrl, initialPdfPageNo]);

  const goToPage = (page: number) => {
    if (page < 1) {
      return;
    }
    if (pageCount && page > pageCount) {
      return;
    }
    setCurrentPdfPageNo(page);
    setPageInputValue("");
  };

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-[rgba(57,130,152,0.16)] bg-white",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(57,130,152,0.14)] bg-[rgb(249,252,252)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(currentPdfPageNo - 1)}
              disabled={currentPdfPageNo <= 1}
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <div className="flex items-center gap-1 text-sm text-slate-700">
              <Input
                type="text"
                className="h-8 w-14 rounded-lg border-[rgba(57,130,152,0.16)] text-center"
                value={
                  pageInputValue !== ""
                    ? pageInputValue
                    : String(currentPdfPageNo)
                }
                onChange={(event) => setPageInputValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") {
                    return;
                  }
                  const page = parseInt(pageInputValue, 10);
                  if (!Number.isNaN(page)) {
                    goToPage(page);
                  }
                }}
                onBlur={() => setPageInputValue("")}
                onFocus={() => setPageInputValue(String(currentPdfPageNo))}
              />
              <span className="text-slate-500">/ {pageCount ?? "?"}</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(currentPdfPageNo + 1)}
              disabled={pageCount ? currentPdfPageNo >= pageCount : false}
            >
              <ChevronRightIcon className="size-4" />
            </Button>
          </div>

          <div className="hidden min-w-0 md:block">
            <div className="truncate text-sm font-medium text-slate-900">
              {originTitle}
            </div>
            <div className="truncate text-xs text-slate-500">
              {originFilename}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={mode === "compare" ? "default" : "outline"}
            size="sm"
            className="h-8 rounded-xl"
            onClick={() => setMode("compare")}
          >
            <ScrollTextIcon className="mr-1.5 size-4" />
            原文结构
          </Button>
          <Button
            variant={mode === "translation" ? "default" : "outline"}
            size="sm"
            className="h-8 rounded-xl"
            onClick={() => setMode("translation")}
          >
            <LanguagesIcon className="mr-1.5 size-4" />
            中文翻译
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {mode === "compare" ? (
          <KnowledgeSidePane
            currentPdfPageNo={currentPdfPageNo}
            documentUrl={documentUrl}
            mode={mode}
            originFilename={originFilename}
            originTitle={originTitle}
            knowledgeSpaceId={knowledgeSpaceId}
            interactive={interactive}
            highlightable={highlightable}
            excerptable={excerptable}
            fluid
            bordered={false}
            onPageDataChange={(pageData) => {
              setPageCount(pageData?.page_count ?? null);
            }}
          />
        ) : (
          <KnowledgeTranslationWorkspace
            documentUrl={documentUrl}
            currentPdfPageNo={currentPdfPageNo}
            sourceLanguage={translationSourceLanguage}
            onSourceLanguageChange={setTranslationSourceLanguage}
            onPageDataChange={(pageData) => {
              setPageCount(pageData?.page_count ?? null);
            }}
          />
        )}
      </div>
    </div>
  );
}
