"use client";

import { FileTextIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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

type TranslationLayoutItem = {
  contextParagraph: ContextParagraph;
  paragraph: KnowledgeStructuredParagraph;
  baseHeight: number;
  overflowHeight: number;
  showTranslation: boolean;
  textLeft: number;
  textTop: number;
  textWidth: number;
};

const TRANSLATION_BLOCK_MARGIN_TOP = 10;
const TRANSLATION_BLOCK_MARGIN_BOTTOM = 16;
const TRANSLATION_LINE_HEIGHT = 22;

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

function paragraphFontSize(paragraph: KnowledgeStructuredParagraph) {
  const height = paragraph.bbox?.height ?? 42;
  return Math.max(14, Math.min(24, height * 0.34));
}

function paragraphLocationLabel(paragraph: ContextParagraph) {
  const parts: string[] = [];
  if (paragraph.pdfPageNo) {
    parts.push(`PDF 第 ${paragraph.pdfPageNo} 页`);
  } else if (paragraph.pageNo) {
    parts.push(`第 ${paragraph.pageNo} 页`);
  }
  if (paragraph.paragraphNo) {
    parts.push(`第 ${paragraph.paragraphNo} 段`);
  }
  return parts.join(" · ") || "当前段落";
}

export function KnowledgeSidePane({
  currentPdfPageNo,
  documentUrl,
  mode,
  originFilename,
  originTitle,
  referencePageHeight,
  referencePageWidth,
}: {
  currentPdfPageNo: number | null;
  documentUrl: string;
  mode: KnowledgeSidePaneMode;
  originFilename: string;
  originTitle: string;
  referencePageHeight?: number | null;
  referencePageWidth?: number | null;
}) {
  const router = useRouter();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const translationBlockRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const createDerivedMutation = useCreateUserDerivedKnowledge();
  const [pageState, setPageState] = useState<PageState>({ status: "idle" });
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
  const [translationBlockHeights, setTranslationBlockHeights] = useState<
    Record<string, number>
  >({});

  useEffect(() => {
    if (!currentPdfPageNo) {
      setPageState({ status: "idle" });
      return;
    }

    let cancelled = false;
    setPageState({ status: "loading" });
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

  const pageData = pageState.status === "ready" ? pageState.data : null;
  const pageWidth = pageData?.page_meta?.page_width ?? 0;
  const pageHeight = pageData?.page_meta?.page_height ?? 0;

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
    ? translationCache[translationCacheKey] ?? null
    : null;

  useEffect(() => {
    setTranslationBlockHeights({});
    translationBlockRefs.current = {};
  }, [translationCacheKey]);

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
  ]);

  const activeKey = useMemo(
    () => contextMenu?.paragraph.key ?? hoveredKey,
    [contextMenu?.paragraph.key, hoveredKey],
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
        toast.success("已创建摘录，正在跳转个人知识库");
        router.push(
          `/workspace/personal-knowledge?record=${encodeURIComponent(result.record.id)}`,
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

  const renderCompareContent = () => {
    if (!pageData || pageWidth <= 0 || pageHeight <= 0) {
      return null;
    }

    return (
      <div
        ref={viewportRef}
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-4 pl-2 pr-3"
      >
        <KnowledgePageSurface
          height={canvasMetrics.height || pageHeight}
          width={canvasMetrics.width || pageWidth}
        >
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{
              width: `${pageWidth}px`,
              height: `${pageHeight}px`,
              transform: `scale(${canvasMetrics.scaleX}, ${canvasMetrics.scaleY})`,
            }}
          >
            {(pageData.paragraphs ?? []).map((paragraph) => {
              const bbox = paragraph.bbox;
              if (!bbox) {
                return null;
              }

              const contextParagraph = buildContextParagraph(pageData, paragraph);
              const isActive = activeKey === contextParagraph.key;
              return (
                <div
                  key={contextParagraph.key}
                  className={cn(
                    "absolute cursor-context-menu overflow-hidden rounded-sm border text-left transition-colors select-none",
                    isActive
                      ? "border-emerald-500/95 bg-emerald-50/70"
                      : "border-transparent bg-transparent hover:border-emerald-400/90 hover:bg-emerald-50/45",
                  )}
                  style={{
                    left: `${bbox.x}px`,
                    top: `${bbox.y}px`,
                    width: `${bbox.width}px`,
                    height: `${Math.max(bbox.height, 24)}px`,
                    padding: "2px 4px",
                    fontSize: `${paragraphFontSize(paragraph)}px`,
                    lineHeight: 1.42,
                    letterSpacing: "0.01em",
                    color: "#1c1917",
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
                >
                  <div className="pointer-events-none whitespace-pre-wrap break-words">
                    {paragraph.text}
                  </div>
                </div>
              );
            })}
          </div>
        </KnowledgePageSurface>
      </div>
    );
  };

  const renderTranslationContent = () => {
    if (!pageData || pageWidth <= 0 || pageHeight <= 0) {
      return null;
    }

    const scale = canvasMetrics.scaleX || 1;
    const translationFontSize = 15;

    const layoutItems: TranslationLayoutItem[] = [];
    let extraOffset = 0;

    for (const paragraph of pageData.paragraphs ?? []) {
      const bbox = paragraph.bbox;
      if (!bbox) {
        continue;
      }

      const contextParagraph = buildContextParagraph(pageData, paragraph);
      const translationText = translationMap?.[contextParagraph.key] ?? "";
      const showTranslation = translationText.length > 0;
      const textLeft = bbox.x * scale;
      const textTop = bbox.y * scale + extraOffset;
      const textWidth = bbox.width * scale;
      const baseHeight = bbox.height * scale;
      const blockHeight = translationBlockHeights[contextParagraph.key] ?? baseHeight;
      const overflowHeight = Math.max(0, blockHeight - baseHeight);

      layoutItems.push({
        contextParagraph,
        paragraph,
        baseHeight,
        overflowHeight,
        showTranslation,
        textLeft,
        textTop,
        textWidth,
      });

      if (overflowHeight > 0) {
        extraOffset += overflowHeight;
      }
    }

    const totalHeight = Math.max(
      pageHeight * scale,
      ...layoutItems.map((item) => item.textTop + item.baseHeight + item.overflowHeight),
    );

    return (
      <div
        ref={viewportRef}
        className="min-h-0 flex-1 overflow-y-auto p-4 pl-2 pr-3"
      >
        <div className="flex min-w-0 justify-center">
          <KnowledgePageSurface
            width={canvasMetrics.width || pageWidth}
            height={totalHeight}
            className="overflow-visible"
            style={{
              minHeight: `${totalHeight}px`,
            }}
          >
            <div className="relative" style={{ height: `${totalHeight}px` }}>
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

              {layoutItems.map((item) => {
                const isActive = activeKey === item.contextParagraph.key;
                return (
                  <div
                    key={item.contextParagraph.key}
                    ref={(node) => {
                      translationBlockRefs.current[item.contextParagraph.key] = node;
                    }}
                    className={cn(
                      "absolute rounded-md border border-transparent text-left transition-colors",
                      isActive
                        ? "bg-emerald-50/55"
                        : "hover:border-emerald-300/70 hover:bg-emerald-50/35",
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
                        fontSize: `${paragraphFontSize(item.paragraph) * scale}px`,
                        lineHeight: 1.42,
                        letterSpacing: "0.01em",
                      }}
                    >
                      {item.paragraph.text}
                    </div>

                    {item.showTranslation ? (
                      <div
                        className="whitespace-pre-wrap break-words text-emerald-700"
                        style={{
                          marginTop: `${TRANSLATION_BLOCK_MARGIN_TOP}px`,
                          marginBottom: `${TRANSLATION_BLOCK_MARGIN_BOTTOM}px`,
                          fontSize: `${translationFontSize}px`,
                          lineHeight: `${TRANSLATION_LINE_HEIGHT}px`,
                        }}
                      >
                        {translationMap?.[item.contextParagraph.key]}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </KnowledgePageSurface>
        </div>
      </div>
    );
  };

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
  }, [mode, translationBlockHeights, translationMap, canvasMetrics.scaleX]);

  return (
    <div
      className="relative min-h-0 shrink-0 border-l bg-[#f6f1e8]"
      style={{ width: `${KNOWLEDGE_SIDE_PANE_WIDTH}px` }}
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
          (mode === "compare" ? renderCompareContent() : renderTranslationContent())}
      </div>

      {renderContextMenu()}
    </div>
  );
}
