"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  FileTextIcon,
  LanguagesIcon,
  Loader2Icon,
  ScanSearchIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeStructuredPageForDocumentUrl,
  resolveKnowledgeDocumentUrl,
  translateKnowledgeParagraphsToChineseForDocumentUrl,
  type KnowledgeStructuredPage,
  type KnowledgeStructuredParagraph,
} from "@/core/knowledge/api";
import { useCreateUserDerivedKnowledge } from "@/core/knowledge/user-hooks";
import { cn } from "@/lib/utils";

import { KnowledgePageSurface } from "./knowledge-page-surface";

type ReaderMode = "pdf" | "translation";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeStructuredPage };

type ContextParagraph = {
  key: string;
  pdfPageNo: number | null;
  pageNo: number | null;
  paragraphNo: number | null;
  text: string;
};

type ContextMenuState = {
  x: number;
  y: number;
  paragraph: ContextParagraph;
};

type TranslationLayoutItem = {
  contextParagraph: ContextParagraph;
  paragraph: KnowledgeStructuredParagraph;
  baseHeight: number;
  overflowHeight: number;
  textLeft: number;
  textTop: number;
  textWidth: number;
  translatedText: string;
};

const TRANSLATION_LINE_HEIGHT = 1.48;
const TRANSLATION_BLOCK_PADDING_X = 8;
const TRANSLATION_BLOCK_PADDING_Y = 6;

function paragraphKey(
  page: KnowledgeStructuredPage,
  paragraph: KnowledgeStructuredParagraph,
) {
  return `${page.pdf_page_no ?? page.page_no ?? "page"}:${paragraph.paragraph_id ?? paragraph.paragraph_no ?? paragraph.text}`;
}

function buildContextParagraph(
  page: KnowledgeStructuredPage,
  paragraph: KnowledgeStructuredParagraph,
): ContextParagraph {
  return {
    key: paragraphKey(page, paragraph),
    pdfPageNo: page.pdf_page_no ?? null,
    pageNo: page.page_no ?? null,
    paragraphNo: paragraph.paragraph_no ?? null,
    text: paragraph.text,
  };
}

function buildExcerptTitle(originTitle: string, paragraph: ContextParagraph) {
  const location = paragraph.paragraphNo ? `第${paragraph.paragraphNo}段` : "摘录";
  return `${originTitle} ${location}摘录`;
}

function buildExcerptMarkdown(
  originFilename: string,
  title: string,
  paragraph: ContextParagraph,
) {
  const locationParts: string[] = [];
  if (paragraph.pdfPageNo) {
    locationParts.push(`PDF 第 ${paragraph.pdfPageNo} 页`);
  } else if (paragraph.pageNo) {
    locationParts.push(`第 ${paragraph.pageNo} 页`);
  }
  if (paragraph.paragraphNo) {
    locationParts.push(`第 ${paragraph.paragraphNo} 段`);
  }

  return [
    `# ${title}`,
    "",
    `来源：${originFilename}`,
    locationParts.length ? `定位：${locationParts.join(" · ")}` : null,
    "",
    "## 原文摘录",
    "",
    `> ${paragraph.text.replace(/\n/g, "\n> ")}`,
    "",
    "## 我的摘抄笔记",
    "",
    "",
  ]
    .filter((part): part is string => part !== null)
    .join("\n");
}

function characterWidthWeight(character: string) {
  if (!character.trim()) {
    return 0.34;
  }
  if (/[A-Z0-9]/.test(character)) {
    return 0.62;
  }
  if (/[a-z]/.test(character)) {
    return 0.56;
  }
  if (
    /[\u2e80-\u2eff\u2f00-\u2fdf\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/.test(
      character,
    )
  ) {
    return 1;
  }
  return 0.48;
}

function estimateTextHeight(text: string, width: number, fontSize: number) {
  const normalizedWidth = Math.max(width / fontSize, 1);
  const lines = text.split("\n").reduce((total, line) => {
    const lineUnits = Array.from(line).reduce(
      (sum, character) => sum + characterWidthWeight(character),
      0,
    );
    return total + Math.max(1, Math.ceil(lineUnits / normalizedWidth));
  }, 0);
  return lines * fontSize * TRANSLATION_LINE_HEIGHT;
}

function paragraphFontSize(paragraph: KnowledgeStructuredParagraph) {
  const bbox = paragraph.bbox;
  if (!bbox) {
    return 14;
  }

  const availableWidth = Math.max(bbox.width - TRANSLATION_BLOCK_PADDING_X, 18);
  const availableHeight = Math.max(bbox.height - TRANSLATION_BLOCK_PADDING_Y, 14);
  const maxSize = Math.max(9, Math.min(28, Math.floor(availableHeight * 0.72)));
  let low = 8;
  let high = maxSize;
  let best = 8;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const estimatedHeight = estimateTextHeight(paragraph.text, availableWidth, mid);
    if (estimatedHeight <= availableHeight) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return best;
}

export function KnowledgePdfReader({
  documentUrl,
  initialPdfPageNo = 1,
  knowledgeSpaceId,
  originFilename,
  originTitle,
}: {
  documentUrl: string;
  initialPdfPageNo?: number;
  knowledgeSpaceId?: string;
  originFilename: string;
  originTitle: string;
}) {
  const router = useRouter();
  const createDerivedMutation = useCreateUserDerivedKnowledge();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const translationBlockRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const [mode, setMode] = useState<ReaderMode>("pdf");
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number>(
    Math.max(initialPdfPageNo, 1),
  );
  const [pageInputValue, setPageInputValue] = useState("");
  const [pageState, setPageState] = useState<PageState>({ status: "loading" });
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [translationCache, setTranslationCache] = useState<
    Record<string, Record<string, string>>
  >({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
  const [translationBlockHeights, setTranslationBlockHeights] = useState<
    Record<string, number>
  >({});
  const [canvasWidth, setCanvasWidth] = useState(0);

  useEffect(() => {
    setCurrentPdfPageNo(Math.max(initialPdfPageNo, 1));
    setPageInputValue("");
    setPageState({ status: "loading" });
    setContextMenu(null);
    setHoveredKey(null);
  }, [documentUrl, initialPdfPageNo]);

  useEffect(() => {
    let cancelled = false;
    setPageState({ status: "loading" });
    setContextMenu(null);
    setHoveredKey(null);

    getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
      pdfPageNo: currentPdfPageNo,
    })
      .then((data) => {
        if (!cancelled) {
          setPageState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setPageState({
            status: "error",
            message: error.message || "结构化页加载失败",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentPdfPageNo, documentUrl]);

  useEffect(() => {
    const closeMenu = (event: Event) => {
      if (event instanceof PointerEvent && event.button === 2) {
        return;
      }
      if (
        contextMenuRef.current &&
        event.target instanceof Node &&
        contextMenuRef.current.contains(event.target)
      ) {
        return;
      }
      setContextMenu(null);
    };

    window.addEventListener("pointerdown", closeMenu);
    window.addEventListener("scroll", closeMenu, true);
    return () => {
      window.removeEventListener("pointerdown", closeMenu);
      window.removeEventListener("scroll", closeMenu, true);
    };
  }, []);

  const pageData = pageState.status === "ready" ? pageState.data : null;
  const pageCount = pageData?.page_count ?? null;
  const pageWidth = pageData?.page_meta?.page_width ?? 0;
  const pageHeight = pageData?.page_meta?.page_height ?? 0;
  const pageImageUrl = useMemo(
    () => buildKnowledgePageImageURLForDocumentUrl(documentUrl, currentPdfPageNo),
    [currentPdfPageNo, documentUrl],
  );

  const translationCacheKey = useMemo(() => {
    if (!pageData) {
      return null;
    }
    return `${pageData.filename}:${pageData.pdf_page_no ?? pageData.page_no ?? "page"}`;
  }, [pageData]);

  const translationMap = translationCacheKey
    ? translationCache[translationCacheKey] ?? null
    : null;

  const paragraphs = useMemo(
    () =>
      pageData
        ? (pageData.paragraphs ?? [])
            .filter((paragraph) => Boolean(paragraph.bbox))
            .map((paragraph) => ({
              contextParagraph: buildContextParagraph(pageData, paragraph),
              paragraph,
            }))
        : [],
    [pageData],
  );

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !pageWidth) {
      setCanvasWidth(0);
      return;
    }

    const updateCanvasWidth = () => {
      const availableWidth = Math.max(viewport.clientWidth - 24, 1);
      setCanvasWidth(Math.min(availableWidth, pageWidth));
    };

    updateCanvasWidth();
    const observer = new ResizeObserver(updateCanvasWidth);
    observer.observe(viewport);
    return () => {
      observer.disconnect();
    };
  }, [pageWidth, mode, currentPdfPageNo]);

  useEffect(() => {
    setTranslationBlockHeights({});
    translationBlockRefs.current = {};
  }, [translationCacheKey]);

  useEffect(() => {
    if (
      mode !== "translation" ||
      !pageData ||
      !translationCacheKey ||
      translationMap ||
      paragraphs.length === 0
    ) {
      return;
    }

    let cancelled = false;
    setTranslationLoading(true);
    setTranslationError(null);

    translateKnowledgeParagraphsToChineseForDocumentUrl(
      documentUrl,
      paragraphs.map((item) => ({
        key: item.contextParagraph.key,
        text: item.contextParagraph.text,
      })),
    )
      .then((items) => {
        if (cancelled) {
          return;
        }
        const nextMap = Object.fromEntries(
          items
            .filter((item) => item.key && item.translation)
            .map((item) => [item.key, item.translation]),
        );
        setTranslationCache((current) => ({
          ...current,
          [translationCacheKey]: nextMap,
        }));
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setTranslationError(error.message || "翻译失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTranslationLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [documentUrl, mode, pageData, paragraphs, translationCacheKey, translationMap]);

  const activeKey = contextMenu?.paragraph.key ?? hoveredKey;

  const goToPage = useCallback(
    (page: number) => {
      if (page < 1) {
        return;
      }
      if (pageCount && page > pageCount) {
        return;
      }
      setCurrentPdfPageNo(page);
      setPageInputValue("");
    },
    [pageCount],
  );

  const openContextMenu = useCallback(
    (paragraph: ContextParagraph, position: { x: number; y: number }) => {
      setContextMenu({
        x: position.x,
        y: position.y,
        paragraph,
      });
    },
    [],
  );

  const handleCreateExcerpt = useCallback(
    async (paragraph: ContextParagraph) => {
      const title = buildExcerptTitle(originTitle, paragraph);
      const content = buildExcerptMarkdown(originFilename, title, paragraph);
      const resolvedDocument = resolveKnowledgeDocumentUrl(documentUrl);

      try {
        const result = await createDerivedMutation.mutateAsync({
          title,
          content,
          sourceKind: "excerpt",
          knowledgeSpaceId,
          originScope: resolvedDocument?.scope ?? "global",
          originDocId: resolvedDocument?.filename ?? pageData?.doc_id ?? null,
          originFilename: pageData?.filename ?? originFilename,
          originAnchor: {
            pdf_page_no: paragraph.pdfPageNo,
            page_no: paragraph.pageNo,
            paragraph_no: paragraph.paragraphNo,
            text: paragraph.text,
          },
        });
        setContextMenu(null);
        toast.success("已创建摘录，正在跳转笔记");
        router.push(
          `/workspace/notes?space=${encodeURIComponent(
            knowledgeSpaceId ?? result.record.knowledge_space_id ?? "",
          )}&record=${encodeURIComponent(result.record.id)}`,
        );
      } catch (error) {
        console.error(error);
        toast.error(error instanceof Error ? error.message : "创建摘录失败");
      }
    },
    [
      createDerivedMutation,
      documentUrl,
      knowledgeSpaceId,
      originFilename,
      originTitle,
      pageData?.doc_id,
      pageData?.filename,
      router,
    ],
  );

  const renderContextMenu = () => {
    if (!contextMenu) {
      return null;
    }

    const menuWidth = 118;
    const left =
      typeof window !== "undefined"
        ? Math.min(contextMenu.x, window.innerWidth - menuWidth - 12)
        : contextMenu.x;
    const top =
      typeof window !== "undefined"
        ? Math.min(contextMenu.y, window.innerHeight - 56)
        : contextMenu.y;

    return (
      <div
        ref={contextMenuRef}
        className="fixed z-50 rounded-2xl border border-stone-200 bg-white p-1.5 shadow-[0_18px_40px_-22px_rgba(28,25,23,0.4)]"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
      >
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-9 rounded-xl px-3 text-stone-800 hover:bg-stone-100"
          disabled={createDerivedMutation.isPending}
          onClick={() => void handleCreateExcerpt(contextMenu.paragraph)}
        >
          {createDerivedMutation.isPending ? (
            <Loader2Icon className="mr-1.5 size-4 animate-spin" />
          ) : (
            <FileTextIcon className="mr-1.5 size-4" />
          )}
          摘录
        </Button>
      </div>
    );
  };

  const displayScale = pageWidth > 0
    ? Math.min((canvasWidth || pageWidth) / pageWidth, 1)
    : 1;

  const translationLayoutItems = useMemo(() => {
    if (!pageData || pageWidth <= 0 || pageHeight <= 0) {
      return [];
    }

    const items: TranslationLayoutItem[] = [];
    let extraOffset = 0;

    for (const paragraph of pageData.paragraphs ?? []) {
      const bbox = paragraph.bbox;
      if (!bbox) {
        continue;
      }

      const contextParagraph = buildContextParagraph(pageData, paragraph);
      const translatedText = translationMap
        ? (translationMap[contextParagraph.key] ?? paragraph.text)
        : "";
      const textLeft = bbox.x * displayScale;
      const textTop = bbox.y * displayScale + extraOffset;
      const textWidth = bbox.width * displayScale;
      const baseHeight = bbox.height * displayScale;
      const blockHeight = translationBlockHeights[contextParagraph.key] ?? baseHeight;
      const overflowHeight = Math.max(0, blockHeight - baseHeight);

      items.push({
        contextParagraph,
        paragraph,
        baseHeight,
        overflowHeight,
        textLeft,
        textTop,
        textWidth,
        translatedText,
      });

      if (overflowHeight > 0) {
        extraOffset += overflowHeight;
      }
    }

    return items;
  }, [
    displayScale,
    pageData,
    pageHeight,
    pageWidth,
    translationBlockHeights,
    translationMap,
  ]);

  const translationCanvasHeight = useMemo(() => {
    if (!pageHeight) {
      return 0;
    }

    return Math.max(
      pageHeight * displayScale,
      ...translationLayoutItems.map((item) => item.textTop + item.baseHeight + item.overflowHeight),
    );
  }, [displayScale, pageHeight, translationLayoutItems]);

  useLayoutEffect(() => {
    if (mode !== "translation") {
      return;
    }

    const nextHeights: Record<string, number> = {};
    for (const [key, element] of Object.entries(translationBlockRefs.current)) {
      if (!element) {
        continue;
      }
      nextHeights[key] = Math.ceil(element.getBoundingClientRect().height);
    }

    const currentKeys = Object.keys(translationBlockHeights);
    const nextKeys = Object.keys(nextHeights);
    const changed =
      currentKeys.length !== nextKeys.length ||
      nextKeys.some((key) => translationBlockHeights[key] !== nextHeights[key]);

    if (changed) {
      setTranslationBlockHeights(nextHeights);
    }
  }, [mode, translationBlockHeights, translationLayoutItems]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-[rgba(57,130,152,0.16)] bg-white">
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
                value={pageInputValue !== "" ? pageInputValue : String(currentPdfPageNo)}
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

        <div className="flex items-center gap-3">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={mode}
            onValueChange={(value) => {
              if (value === "pdf" || value === "translation") {
                setMode(value);
              }
            }}
          >
            <ToggleGroupItem value="pdf">
              <ScanSearchIcon className="mr-1.5 size-4" />
              原页
            </ToggleGroupItem>
            <ToggleGroupItem value="translation">
              <LanguagesIcon className="mr-1.5 size-4" />
              中文译文
            </ToggleGroupItem>
          </ToggleGroup>
          <div className="hidden text-xs text-slate-500 md:block">
            原页模式支持 hover 绿框与右键摘录
          </div>
        </div>
      </div>

      <div
        ref={viewportRef}
        className={cn(
          "relative min-h-0 flex-1 overflow-auto",
          mode === "pdf" ? "bg-[rgb(243,246,248)]" : "bg-[#f6f1e8]",
        )}
      >
        {pageState.status === "loading" && (
          <div className="flex h-full items-center justify-center text-sm text-stone-500">
            <Loader2Icon className="mr-2 size-4 animate-spin" />
            正在加载页面...
          </div>
        )}

        {pageState.status === "error" && (
          <div className="flex h-full items-center justify-center px-6 text-sm text-red-600">
            {pageState.message}
          </div>
        )}

        {pageState.status === "ready" && mode === "pdf" && (
          <div className="flex min-h-full items-start justify-center p-4 md:p-6">
            <div className="relative max-w-full">
              <img
                src={pageImageUrl}
                alt={`${pageState.data.title} 第 ${currentPdfPageNo} 页`}
                className="block max-w-full rounded-md bg-white shadow-[0_24px_50px_-30px_rgba(15,23,42,0.45)]"
              />
              <div className="absolute inset-0">
                {paragraphs.map(({ contextParagraph, paragraph }) => {
                  const bbox = paragraph.bbox;
                  if (!bbox || pageWidth <= 0 || pageHeight <= 0) {
                    return null;
                  }

                  const isActive = activeKey === contextParagraph.key;
                  return (
                    <div
                      key={contextParagraph.key}
                      className={cn(
                        "absolute rounded-[6px] border-2 transition-all",
                        isActive
                          ? "border-emerald-500 bg-emerald-400/12 shadow-[0_0_0_1px_rgba(16,185,129,0.12)]"
                          : "border-transparent bg-transparent hover:border-emerald-400/90 hover:bg-emerald-300/10",
                      )}
                      style={{
                        left: `${(bbox.x / pageWidth) * 100}%`,
                        top: `${(bbox.y / pageHeight) * 100}%`,
                        width: `${(bbox.width / pageWidth) * 100}%`,
                        height: `${(bbox.height / pageHeight) * 100}%`,
                      }}
                      onMouseEnter={() => setHoveredKey(contextParagraph.key)}
                      onMouseLeave={() =>
                        setHoveredKey((current) =>
                          current === contextParagraph.key ? null : current,
                        )
                      }
                      onPointerDownCapture={(event) => {
                        if (event.button !== 2) {
                          return;
                        }
                        event.preventDefault();
                        event.stopPropagation();
                        openContextMenu(contextParagraph, {
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }}
                      onContextMenuCapture={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        openContextMenu(contextParagraph, {
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {pageState.status === "ready" && mode === "translation" && (
          <div className="min-h-full p-4 md:p-6">
            <div className="flex justify-center">
              <KnowledgePageSurface
                width={pageWidth * displayScale}
                height={translationCanvasHeight}
                className="overflow-visible shadow-[0_24px_50px_-30px_rgba(15,23,42,0.28)]"
                style={{
                  minHeight: `${translationCanvasHeight}px`,
                }}
              >
                <div
                  className="relative"
                  style={{
                    width: `${pageWidth * displayScale}px`,
                    height: `${translationCanvasHeight}px`,
                  }}
                >
                  {translationError && !translationMap ? (
                    <div className="mx-4 mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                      {translationError}
                    </div>
                  ) : null}

                  {translationLoading && !translationMap ? (
                    <div className="mx-4 mt-4 flex min-h-[120px] items-center justify-center rounded-2xl border border-stone-200 bg-stone-50 text-sm text-stone-500">
                      <Loader2Icon className="mr-2 size-4 animate-spin" />
                      正在翻译本页为中文...
                    </div>
                  ) : null}

                  {translationLayoutItems.map((item) => {
                    const isActive = activeKey === item.contextParagraph.key;
                    const fontSize = Math.max(
                      Math.min(paragraphFontSize(item.paragraph) * displayScale, 20),
                      12,
                    );

                    return (
                      <div
                        key={item.contextParagraph.key}
                        ref={(node) => {
                          translationBlockRefs.current[item.contextParagraph.key] = node;
                        }}
                        className={cn(
                          "absolute rounded-md border text-left transition-colors",
                          isActive
                            ? "border-emerald-400/70 bg-emerald-50/60"
                            : "border-transparent hover:border-emerald-300/70 hover:bg-emerald-50/35",
                        )}
                        style={{
                          left: `${Math.max(item.textLeft - 4, 0)}px`,
                          top: `${Math.max(item.textTop - 4, 0)}px`,
                          width: `${item.textWidth + 8}px`,
                          padding: "4px",
                        }}
                        onMouseEnter={() => setHoveredKey(item.contextParagraph.key)}
                        onMouseLeave={() =>
                          setHoveredKey((current) =>
                            current === item.contextParagraph.key ? null : current,
                          )
                        }
                        onPointerDownCapture={(event) => {
                          if (event.button !== 2) {
                            return;
                          }
                          event.preventDefault();
                          event.stopPropagation();
                          openContextMenu(item.contextParagraph, {
                            x: event.clientX,
                            y: event.clientY,
                          });
                        }}
                        onContextMenuCapture={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          openContextMenu(item.contextParagraph, {
                            x: event.clientX,
                            y: event.clientY,
                          });
                        }}
                      >
                        <div
                          className="whitespace-pre-wrap break-words text-stone-800"
                          style={{
                            minHeight: `${item.baseHeight}px`,
                            fontSize: `${fontSize}px`,
                            lineHeight: TRANSLATION_LINE_HEIGHT,
                            letterSpacing: "0.01em",
                          }}
                        >
                          {item.translatedText}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </KnowledgePageSurface>
            </div>
          </div>
        )}
      </div>

      {renderContextMenu()}
    </div>
  );
}
