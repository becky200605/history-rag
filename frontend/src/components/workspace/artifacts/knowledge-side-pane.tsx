"use client";

import { FileTextIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  getKnowledgeStructuredPageForDocumentUrl,
  resolveKnowledgeDocumentUrl,
  translateKnowledgeParagraphsToChineseForDocumentUrl,
  type KnowledgeStructuredPage,
  type KnowledgeStructuredParagraph,
} from "@/core/knowledge/api";
import { useCreateUserDerivedKnowledge } from "@/core/knowledge/user-hooks";
import { cn } from "@/lib/utils";

import { KNOWLEDGE_SIDE_PANE_WIDTH } from "./knowledge-layout";
import { KnowledgePageSurface } from "./knowledge-page-surface";

export type KnowledgeSidePaneMode = "compare" | "translation";

type PageState =
  | { status: "idle" | "loading" }
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

type CompareLayoutItem = {
  key: string;
  contextParagraph: ContextParagraph;
  paragraph: KnowledgeStructuredParagraph;
  bbox: NonNullable<KnowledgeStructuredParagraph["bbox"]>;
  source: "current" | "previous-spill";
  textLeft: number;
  textTop: number;
  visibleTop: number;
  visibleHeight: number;
  continuesFromPreviousPage: boolean;
  continuesToNextPage: boolean;
};

const COMPARE_TEXT_PADDING_X = 8;
const COMPARE_TEXT_PADDING_Y = 4;
const COMPARE_LINE_HEIGHT = 1.42;
const PAGE_OVERFLOW_TOLERANCE = 8;

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
  const location = paragraph.paragraphNo
    ? `第${paragraph.paragraphNo}段`
    : "摘录";
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
  return lines * fontSize * COMPARE_LINE_HEIGHT;
}

function paragraphFontSize(paragraph: KnowledgeStructuredParagraph) {
  const bbox = paragraph.bbox;
  if (!bbox) {
    return 14;
  }

  const availableWidth = Math.max(bbox.width - COMPARE_TEXT_PADDING_X, 18);
  const availableHeight = Math.max(bbox.height - COMPARE_TEXT_PADDING_Y, 14);
  const maxSize = Math.max(9, Math.min(28, Math.floor(availableHeight * 0.72)));
  let low = 8;
  let high = maxSize;
  let best = 8;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const estimatedHeight = estimateTextHeight(
      paragraph.text,
      availableWidth,
      mid,
    );
    if (estimatedHeight <= availableHeight) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return best;
}

function buildCompareLayoutItems(
  currentPage: KnowledgeStructuredPage,
  previousPage: KnowledgeStructuredPage | null,
) {
  const currentPageHeight = currentPage.page_meta?.page_height ?? 0;
  if (currentPageHeight <= 0) {
    return [];
  }

  const layoutItems: CompareLayoutItem[] = [];

  for (const paragraph of currentPage.paragraphs ?? []) {
    const bbox = paragraph.bbox;
    if (!bbox) {
      continue;
    }

    const textTop = bbox.y;
    const visibleTop = Math.max(textTop, 0);
    const visibleBottom = Math.min(textTop + bbox.height, currentPageHeight);
    if (visibleBottom <= visibleTop) {
      continue;
    }

    layoutItems.push({
      key: paragraphKey(currentPage, paragraph),
      contextParagraph: buildContextParagraph(currentPage, paragraph),
      paragraph,
      bbox,
      source: "current",
      textLeft: bbox.x,
      textTop,
      visibleTop,
      visibleHeight: visibleBottom - visibleTop,
      continuesFromPreviousPage: textTop < -PAGE_OVERFLOW_TOLERANCE,
      continuesToNextPage:
        textTop + bbox.height > currentPageHeight + PAGE_OVERFLOW_TOLERANCE,
    });
  }

  const previousPageHeight = previousPage?.page_meta?.page_height ?? 0;
  if (previousPage && previousPageHeight > 0) {
    for (const paragraph of previousPage.paragraphs ?? []) {
      const bbox = paragraph.bbox;
      if (!bbox) {
        continue;
      }
      if (
        bbox.y + bbox.height <=
        previousPageHeight + PAGE_OVERFLOW_TOLERANCE
      ) {
        continue;
      }

      const textTop = bbox.y - previousPageHeight;
      const visibleTop = Math.max(textTop, 0);
      const visibleBottom = Math.min(textTop + bbox.height, currentPageHeight);
      if (visibleBottom <= visibleTop) {
        continue;
      }

      layoutItems.push({
        key: `${paragraphKey(previousPage, paragraph)}:spill-${currentPage.pdf_page_no ?? currentPage.page_no ?? "page"}`,
        contextParagraph: buildContextParagraph(previousPage, paragraph),
        paragraph,
        bbox,
        source: "previous-spill",
        textLeft: bbox.x,
        textTop,
        visibleTop,
        visibleHeight: visibleBottom - visibleTop,
        continuesFromPreviousPage: true,
        continuesToNextPage:
          textTop + bbox.height > currentPageHeight + PAGE_OVERFLOW_TOLERANCE,
      });
    }
  }

  return layoutItems.sort((left, right) => {
    if (left.visibleTop !== right.visibleTop) {
      return left.visibleTop - right.visibleTop;
    }
    if (left.textLeft !== right.textLeft) {
      return left.textLeft - right.textLeft;
    }
    return left.source.localeCompare(right.source);
  });
}

export function KnowledgeSidePane({
  currentPdfPageNo,
  documentUrl,
  mode,
  originFilename,
  originTitle,
  knowledgeSpaceId,
  referencePageHeight,
  referencePageWidth,
  translationSourceLanguageHint,
  interactive = true,
  highlightable,
  excerptable,
  onPageDataChange,
  fluid = false,
  bordered = true,
}: {
  currentPdfPageNo: number | null;
  documentUrl: string;
  mode: KnowledgeSidePaneMode;
  originFilename: string;
  originTitle: string;
  knowledgeSpaceId?: string;
  referencePageHeight?: number | null;
  referencePageWidth?: number | null;
  translationSourceLanguageHint?: string;
  interactive?: boolean;
  highlightable?: boolean;
  excerptable?: boolean;
  onPageDataChange?: (page: KnowledgeStructuredPage | null) => void;
  fluid?: boolean;
  bordered?: boolean;
}) {
  const router = useRouter();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const createDerivedMutation = useCreateUserDerivedKnowledge();
  const [pageState, setPageState] = useState<PageState>({ status: "idle" });
  const [previousPageData, setPreviousPageData] =
    useState<KnowledgeStructuredPage | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [canvasMetrics, setCanvasMetrics] = useState({
    width: 0,
    height: 0,
    scaleX: 1,
    scaleY: 1,
  });
  const [translationCache, setTranslationCache] = useState<
    Record<string, Record<string, string>>
  >({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
  const isHighlightable = highlightable ?? interactive;
  const isExcerptable = excerptable ?? interactive;

  useEffect(() => {
    if (!currentPdfPageNo) {
      setPageState({ status: "idle" });
      setPreviousPageData(null);
      return;
    }

    let cancelled = false;
    setPageState({ status: "loading" });
    setPreviousPageData(null);

    const previousPagePromise =
      currentPdfPageNo > 1
        ? getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
            pdfPageNo: currentPdfPageNo - 1,
          }).catch(() => null)
        : Promise.resolve(null);

    Promise.all([
      getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
        pdfPageNo: currentPdfPageNo,
      }),
      previousPagePromise,
    ])
      .then(([data, previousPage]) => {
        if (cancelled) {
          return;
        }
        setPreviousPageData(previousPage);
        setPageState({ status: "ready", data });
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setPreviousPageData(null);
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

  const pageData = pageState.status === "ready" ? pageState.data : null;
  const pageWidth = pageData?.page_meta?.page_width ?? 0;
  const pageHeight = pageData?.page_meta?.page_height ?? 0;
  const compareLayoutItems = useMemo(
    () => (pageData ? buildCompareLayoutItems(pageData, previousPageData) : []),
    [pageData, previousPageData],
  );

  const paragraphs = useMemo(
    () =>
      pageData
        ? (pageData.paragraphs ?? []).map((paragraph) =>
            buildContextParagraph(pageData, paragraph),
          )
        : [],
    [pageData],
  );

  const translationCacheKey = useMemo(() => {
    if (!pageData) {
      return null;
    }
    return `${pageData.filename}:${pageData.pdf_page_no ?? pageData.page_no ?? "page"}`;
  }, [pageData]);

  const translationMap = translationCacheKey
    ? (translationCache[translationCacheKey] ?? null)
    : null;

  useEffect(() => {
    if (!pageData || !pageWidth || !pageHeight) {
      setCanvasMetrics({
        width: 0,
        height: 0,
        scaleX: 1,
        scaleY: 1,
      });
      return;
    }

    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const updateScale = () => {
      const availableWidth = Math.max(viewport.clientWidth - 8, 1);
      const availableHeight = Math.max(viewport.clientHeight - 8, 1);

      if (mode === "translation") {
        const referenceWidth = referencePageWidth ?? pageWidth;
        const referenceHeight = referencePageHeight ?? pageHeight;
        const translationScale = Math.min(
          availableWidth / referenceWidth,
          availableHeight / referenceHeight,
          1,
        );
        const targetWidth = referenceWidth * translationScale;
        const targetHeight = referenceHeight * translationScale;
        setCanvasMetrics({
          width: targetWidth,
          height: targetHeight,
          scaleX: targetWidth / pageWidth,
          scaleY: targetHeight / pageHeight,
        });
        return;
      }

      if (referencePageWidth && referencePageHeight) {
        const boundedScale = Math.min(
          availableWidth / referencePageWidth,
          availableHeight / referencePageHeight,
          1,
        );
        const targetWidth = referencePageWidth * boundedScale;
        const targetHeight = referencePageHeight * boundedScale;
        setCanvasMetrics({
          width: targetWidth,
          height: targetHeight,
          scaleX: targetWidth / pageWidth,
          scaleY: targetHeight / pageHeight,
        });
        return;
      }

      const nextScale = Math.min(
        availableWidth / pageWidth,
        availableHeight / pageHeight,
        1,
      );
      setCanvasMetrics({
        width: pageWidth * nextScale,
        height: pageHeight * nextScale,
        scaleX: nextScale,
        scaleY: nextScale,
      });
    };

    updateScale();
    const observer = new ResizeObserver(updateScale);
    observer.observe(viewport);
    return () => {
      observer.disconnect();
    };
  }, [
    mode,
    pageData,
    pageHeight,
    pageWidth,
    referencePageHeight,
    referencePageWidth,
  ]);

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
      paragraphs.map((paragraph) => ({
        key: paragraph.key,
        text: paragraph.text,
      })),
      {
        sourceLanguageHint: translationSourceLanguageHint,
      },
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
  }, [
    documentUrl,
    mode,
    pageData,
    paragraphs,
    translationCacheKey,
    translationMap,
    translationSourceLanguageHint,
  ]);

  const activeKey = useMemo(
    () => contextMenu?.paragraph.key ?? (isHighlightable ? hoveredKey : null),
    [contextMenu?.paragraph.key, hoveredKey, isHighlightable],
  );

  const openContextMenu = useCallback(
    (
      paragraph: ContextParagraph,
      position: {
        x: number;
        y: number;
      },
    ) => {
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
      originFilename,
      originTitle,
      knowledgeSpaceId,
      pageData?.doc_id,
      pageData?.filename,
      router,
    ],
  );

  const renderContextMenu = () => {
    if (!isExcerptable || !contextMenu) {
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

  const renderCompareContent = () => {
    if (!pageData || pageWidth <= 0 || pageHeight <= 0) {
      return null;
    }

    return (
      <div
        ref={viewportRef}
        className="flex min-h-0 flex-1 items-start justify-center overflow-auto p-4 pr-3 pl-2"
      >
        <KnowledgePageSurface
          height={canvasMetrics.height || pageHeight}
          width={canvasMetrics.width || pageWidth}
        >
          <div
            className="absolute top-0 left-0 origin-top-left"
            style={{
              width: `${pageWidth}px`,
              height: `${pageHeight}px`,
              transform: `scale(${canvasMetrics.scaleX}, ${canvasMetrics.scaleY})`,
            }}
          >
            {compareLayoutItems.map((item) => {
              const isActive = activeKey === item.contextParagraph.key;
              return (
                <div key={item.key}>
                  <div
                    className={cn(
                      "absolute overflow-hidden rounded-md border text-left transition-all duration-200 select-none",
                      isExcerptable && "cursor-context-menu",
                      item.source === "previous-spill"
                        ? "border-dashed"
                        : "border-solid",
                      isActive
                        ? "border-emerald-400 bg-emerald-50/80 shadow-[0_4px_12px_-2px_rgba(16,185,129,0.12)]"
                        : isHighlightable
                          ? "border-transparent bg-transparent hover:border-emerald-200/60 hover:bg-emerald-50/40"
                          : "border-transparent bg-transparent",
                    )}
                    style={{
                      left: `${item.textLeft}px`,
                      top: `${item.textTop}px`,
                      width: `${item.bbox.width}px`,
                      height: `${Math.max(item.bbox.height, 24)}px`,
                      padding: "2px 4px",
                      fontSize: `${paragraphFontSize(item.paragraph)}px`,
                      lineHeight: COMPARE_LINE_HEIGHT,
                      letterSpacing: "0.01em",
                      color: "#1c1917",
                    }}
                    onMouseEnter={
                      isHighlightable
                        ? () => setHoveredKey(item.contextParagraph.key)
                        : undefined
                    }
                    onMouseLeave={
                      isHighlightable
                        ? () =>
                            setHoveredKey((current) =>
                              current === item.contextParagraph.key
                                ? null
                                : current,
                            )
                        : undefined
                    }
                    onPointerDownCapture={
                      isExcerptable
                        ? (event) => {
                            if (event.button !== 2) {
                              return;
                            }
                            event.preventDefault();
                            event.stopPropagation();
                            openContextMenu(item.contextParagraph, {
                              x: event.clientX,
                              y: event.clientY,
                            });
                          }
                        : undefined
                    }
                    onContextMenuCapture={
                      isExcerptable
                        ? (event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            openContextMenu(item.contextParagraph, {
                              x: event.clientX,
                              y: event.clientY,
                            });
                          }
                        : undefined
                    }
                  >
                    <div className="pointer-events-none break-words whitespace-pre-wrap">
                      {item.paragraph.text}
                    </div>
                  </div>

                  {item.continuesFromPreviousPage ? (
                    <div
                      className="pointer-events-none absolute rounded-full bg-amber-100/90 px-2 py-0.5 text-[10px] font-medium text-amber-800 shadow-sm"
                      style={{
                        left: `${Math.max(item.textLeft + 4, 4)}px`,
                        top: `${Math.max(item.visibleTop + 4, 4)}px`,
                      }}
                    >
                      续上页
                    </div>
                  ) : null}

                  {item.continuesToNextPage ? (
                    <div
                      className="pointer-events-none absolute rounded-full bg-sky-100/90 px-2 py-0.5 text-[10px] font-medium text-sky-800 shadow-sm"
                      style={{
                        left: `${Math.max(item.textLeft + 4, 4)}px`,
                        top: `${Math.max(
                          item.visibleTop + item.visibleHeight - 22,
                          item.visibleTop + 4,
                        )}px`,
                      }}
                    >
                      续下页
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </KnowledgePageSurface>
      </div>
    );
  };

  const renderTranslationContent = () => {
    if (!pageData) {
      return null;
    }
    const translationRows = (pageData.paragraphs ?? []).map((paragraph) => {
      const contextParagraph = buildContextParagraph(pageData, paragraph);
      return {
        paragraph,
        contextParagraph,
        translationText: translationMap?.[contextParagraph.key] ?? "",
      };
    });

    return (
      <div
        ref={viewportRef}
        className="min-h-0 flex-1 overflow-y-auto p-4 pr-3 pl-2"
      >
        <div className="mx-auto grid max-w-[1200px] min-w-0 gap-3 md:grid-cols-2">
          <div className="sticky top-0 z-10 rounded-xl border border-slate-200 bg-white/90 px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-500 backdrop-blur-sm">
            原文结构
          </div>
          <div className="sticky top-0 z-10 rounded-xl border border-emerald-200 bg-white/90 px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-emerald-600 backdrop-blur-sm">
            中文翻译
          </div>

          {translationRows.length === 0 ? (
            <div className="md:col-span-2">
              <div className="flex min-h-[180px] items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">
                当前页暂无结构化文本。
              </div>
            </div>
          ) : (
            translationRows.map(
              ({ paragraph, contextParagraph, translationText }) => {
                const isActive = activeKey === contextParagraph.key;
                const interactionProps = {
                  onMouseEnter: isHighlightable
                    ? () => setHoveredKey(contextParagraph.key)
                    : undefined,
                  onMouseLeave: isHighlightable
                    ? () =>
                        setHoveredKey((current) =>
                          current === contextParagraph.key ? null : current,
                        )
                    : undefined,
                  onPointerDownCapture: isExcerptable
                    ? (event: React.PointerEvent<HTMLDivElement>) => {
                        if (event.button !== 2) {
                          return;
                        }
                        event.preventDefault();
                        event.stopPropagation();
                        openContextMenu(contextParagraph, {
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }
                    : undefined,
                  onContextMenuCapture: isExcerptable
                    ? (event: React.MouseEvent<HTMLDivElement>) => {
                        event.preventDefault();
                        event.stopPropagation();
                        openContextMenu(contextParagraph, {
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }
                    : undefined,
                };

                return (
                  <Fragment key={contextParagraph.key}>
                    <div
                      className={cn(
                        "rounded-xl border bg-white p-4 text-left transition-all duration-200 shadow-sm",
                        isExcerptable && "cursor-context-menu",
                        isActive
                          ? "border-emerald-300 ring-1 ring-emerald-300 bg-emerald-50/20"
                          : isHighlightable
                            ? "border-slate-200 hover:border-emerald-200/60 hover:shadow-md"
                            : "border-slate-200",
                      )}
                      {...interactionProps}
                    >
                      <div className="mb-2 text-xs font-medium text-slate-500">
                        第 {paragraph.paragraph_no ?? 1} 段
                      </div>
                      <div className="text-sm leading-7 break-words whitespace-pre-wrap text-slate-800">
                        {paragraph.text}
                      </div>
                    </div>

                    <div
                      className={cn(
                        "rounded-xl border p-4 text-left transition-all duration-200 shadow-[0_4px_12px_rgba(16,185,129,0.03)]",
                        isExcerptable && "cursor-context-menu",
                        isActive
                          ? "border-emerald-400/60 bg-emerald-100/30 ring-1 ring-emerald-300/50 shadow-md"
                          : isHighlightable
                            ? "border-emerald-100 bg-emerald-50/30 hover:border-emerald-300/60 hover:bg-emerald-50/60"
                            : "border-emerald-100 bg-emerald-50/30",
                      )}
                      {...interactionProps}
                    >
                      <div className="mb-2 text-xs font-medium text-emerald-700/80">
                        第 {paragraph.paragraph_no ?? 1} 段译文
                      </div>
                      {translationError && !translationMap ? (
                        <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                          {translationError}
                        </div>
                      ) : translationLoading && !translationMap ? (
                        <div className="flex min-h-[96px] items-center justify-center rounded-xl border border-emerald-200/70 bg-white/70 text-sm text-emerald-700">
                          <Loader2Icon className="mr-2 size-4 animate-spin" />
                          正在翻译本页为中文...
                        </div>
                      ) : (
                        <div className="text-sm leading-7 break-words whitespace-pre-wrap text-emerald-900">
                          {translationText || "该段翻译暂未返回结果。"}
                        </div>
                      )}
                    </div>
                  </Fragment>
                );
              },
            )
          )}
        </div>
      </div>
    );
  };

  useEffect(() => {
    onPageDataChange?.(pageData);
  }, [onPageDataChange, pageData]);

  return (
    <div
      className={cn(
        "relative min-h-0 bg-zinc-50/50",
        fluid ? "w-full" : "shrink-0",
        bordered && "border-l",
      )}
      style={fluid ? undefined : { width: `${KNOWLEDGE_SIDE_PANE_WIDTH}px` }}
    >
      <div className="flex h-full min-h-0 flex-col">
        {pageState.status === "loading" && (
          <div className="flex flex-1 items-center justify-center text-sm text-stone-500">
            <Loader2Icon className="mr-2 size-4 animate-spin" />
            正在载入结构化页...
          </div>
        )}

        {pageState.status === "error" && (
          <div className="flex flex-1 items-center justify-center px-6 text-sm text-red-600">
            {pageState.message}
          </div>
        )}

        {pageState.status === "ready" &&
          (mode === "compare"
            ? renderCompareContent()
            : renderTranslationContent())}
      </div>

      {renderContextMenu()}
    </div>
  );
}
