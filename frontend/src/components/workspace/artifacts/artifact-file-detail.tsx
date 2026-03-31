import {
  ChevronLeftIcon,
  ChevronRightIcon,
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  LanguagesIcon,
  LoaderIcon,
  PackageIcon,
  SquareArrowOutUpRightIcon,
  XIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { useArtifactContent } from "@/core/artifacts/hooks";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeParagraphLocationForDocumentUrl,
  type KnowledgeParagraphLocation,
} from "@/core/knowledge/api";
import { getKnowledgeCitationMeta } from "@/core/knowledge/citation-meta";
import { installSkill } from "@/core/skills/api";
import { streamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileExtension, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";
import { KNOWLEDGE_SIDE_PANE_WIDTH } from "./knowledge-layout";
import { KnowledgePageSurface } from "./knowledge-page-surface";
import {
  KnowledgeSidePane,
  type KnowledgeSidePaneMode,
} from "./knowledge-side-pane";

const PdfViewer = dynamic(
  () => import("./pdf-viewer").then((module) => module.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex size-full items-center justify-center bg-muted/30 p-4 text-sm text-muted-foreground">
        正在加载 PDF...
      </div>
    ),
  },
);

type PreviewVariant = "rendered" | "original" | "split";

export function ArtifactFileDetail({
  className,
  filepath: filepathFromProps,
  threadId,
  onKnowledgeCompareToggle,
}: {
  className?: string;
  filepath: string;
  threadId: string;
  onKnowledgeCompareToggle?: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { artifacts, setOpen, select } = useArtifacts();
  const [markdownPreviewVariant, setMarkdownPreviewVariant] =
    useState<PreviewVariant>("split");

  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);

  const isKnowledgeDoc = useMemo(() => {
    return filepathFromProps.startsWith("knowledge-doc:");
  }, [filepathFromProps]);

  const knowledgeUrl = useMemo(() => {
    if (!isKnowledgeDoc) return null;
    return filepathFromProps.slice("knowledge-doc:".length);
  }, [filepathFromProps, isKnowledgeDoc]);

  const knowledgeCitationMeta = useMemo(() => {
    if (!knowledgeUrl) {
      return null;
    }
    return getKnowledgeCitationMeta(knowledgeUrl);
  }, [knowledgeUrl]);

  const knowledgeSnippet = useMemo(() => {
    if (!isKnowledgeDoc || !knowledgeUrl) return null;
    try {
      const url = new URL(knowledgeUrl, window.location.origin);
      const value = url.searchParams.get("snippet");
      if (!value) return null;
      return value.slice(0, 256);
    } catch {
      return null;
    }
  }, [isKnowledgeDoc, knowledgeUrl]);

  const knowledgePdfPage = useMemo(() => {
    if (!isKnowledgeDoc || !knowledgeUrl) return null;
    try {
      const url = new URL(knowledgeUrl, window.location.origin);
      const pageStr = url.searchParams.get("page");
      if (pageStr) {
        const page = parseInt(pageStr, 10);
        return Number.isNaN(page) ? null : page;
      }
      const pdfPageStr = url.searchParams.get("pdf_page_no");
      if (pdfPageStr) {
        const pdfPage = parseInt(pdfPageStr, 10);
        return Number.isNaN(pdfPage) || pdfPage <= 0 ? null : pdfPage - 1;
      }
      return null;
    } catch {
      return null;
    }
  }, [isKnowledgeDoc, knowledgeUrl]);

  const isKnowledgePdf = useMemo(() => {
    if (!isKnowledgeDoc || !knowledgeUrl) return false;
    try {
      const url = new URL(knowledgeUrl, window.location.origin);
      return url.pathname.toLowerCase().endsWith(".pdf");
    } catch {
      return false;
    }
  }, [isKnowledgeDoc, knowledgeUrl]);

  const knowledgePdfUrl = useMemo(() => {
    if (!isKnowledgePdf || !knowledgeUrl) return null;
    try {
      const url = new URL(knowledgeUrl, window.location.origin);
      url.searchParams.delete("snippet");
      url.searchParams.delete("page");
      url.searchParams.delete("page_no");
      url.searchParams.delete("pdf_page_no");
      url.searchParams.delete("paragraph_no");
      return `${url.pathname}${url.search}`;
    } catch {
      return null;
    }
  }, [isKnowledgePdf, knowledgeUrl]);

  const knowledgePdfLocator = useMemo(() => {
    if (!isKnowledgePdf || !knowledgeUrl) return null;
    try {
      const url = new URL(knowledgeUrl, window.location.origin);
      return {
        filename: decodeURIComponent(url.pathname.split("/").pop() ?? ""),
        pageNo: url.searchParams.get("page_no"),
        pdfPageNo: url.searchParams.get("pdf_page_no"),
        paragraphNo: url.searchParams.get("paragraph_no"),
      };
    } catch {
      return null;
    }
  }, [isKnowledgePdf, knowledgeUrl]);

  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    if (isKnowledgeDoc && knowledgeUrl) {
      try {
        const url = new URL(knowledgeUrl, window.location.origin);
        const filename = url.pathname.split("/").pop();
        return decodeURIComponent(filename ?? knowledgeUrl);
      } catch {
        return knowledgeUrl;
      }
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile, isKnowledgeDoc, knowledgeUrl]);

  const fileBaseName = useMemo(() => {
    const name = getFileName(filepath);
    return name.replace(/\.[^.]+$/, "");
  }, [filepath]);

  const matchingMdArtifact = useMemo(() => {
    if (!artifacts?.length || isKnowledgeDoc) {
      return null;
    }
    const targetName = `${fileBaseName}.md`.toLowerCase();
    return (
      artifacts.find(
        (artifactPath) => getFileName(artifactPath).toLowerCase() === targetName,
      ) ?? null
    );
  }, [artifacts, fileBaseName, isKnowledgeDoc]);

  const { content: convertedArtifactContent } = useArtifactContent({
    threadId,
    filepath: matchingMdArtifact ?? "",
    enabled: Boolean(matchingMdArtifact),
  });

  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);

  const { isCodeFile, language } = useMemo(() => {
    if (isKnowledgeDoc) {
      if (isKnowledgePdf) {
        return { isCodeFile: false, language: "pdf" };
      }
      return { isCodeFile: true, language: "markdown" };
    }
    if (isWriteFile) {
      let fileLanguage = checkCodeFile(filepath).language;
      fileLanguage ??= "text";
      return { isCodeFile: true, language: fileLanguage };
    }
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile, isKnowledgeDoc, isKnowledgePdf]);

  const previewable = useMemo(() => {
    return (language === "html" && !isWriteFile) || language === "markdown";
  }, [isWriteFile, language]);

  const { content } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile && !isKnowledgeDoc,
  });

  const extension = useMemo(() => getFileExtension(filepath), [filepath]);
  const isPdfFile = extension === "pdf";

  const [knowledgeContent, setKnowledgeContent] = useState<string | null>(null);
  const [isKnowledgeLoading, setIsKnowledgeLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<Error | null>(null);

  useEffect(() => {
    if (!isKnowledgeDoc || !knowledgeUrl || isKnowledgePdf) {
      return;
    }
    let cancelled = false;
    setIsKnowledgeLoading(true);
    setKnowledgeError(null);
    fetch(knowledgeUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to load knowledge document");
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) {
          setKnowledgeContent(text);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load knowledge document:", error);
          setKnowledgeError(error as Error);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsKnowledgeLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isKnowledgeDoc, knowledgeUrl, isKnowledgePdf]);

  const displayContent = useMemo(() => {
    if (isKnowledgeDoc) {
      if (knowledgeError) {
        return knowledgeError.message;
      }
      if (isKnowledgeLoading) {
        return "Loading knowledge document...";
      }
      return knowledgeContent ?? "";
    }
    return content ?? "";
  }, [
    content,
    isKnowledgeDoc,
    isKnowledgeLoading,
    knowledgeContent,
    knowledgeError,
  ]);

  const [viewMode, setViewMode] = useState<"code" | "preview">("code");
  const [isInstalling, setIsInstalling] = useState(false);

  useEffect(() => {
    if (language === "markdown") {
      setMarkdownPreviewVariant("split");
    }
  }, [language, filepath]);

  useEffect(() => {
    if (previewable) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [previewable]);

  const handleInstallSkill = useCallback(async () => {
    if (isInstalling) return;

    setIsInstalling(true);
    try {
      const result = await installSkill({
        thread_id: threadId,
        path: filepath,
      });
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message ?? "Failed to install skill");
      }
    } catch (error) {
      console.error("Failed to install skill:", error);
      toast.error("Failed to install skill");
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling]);

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile || isKnowledgeDoc ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select value={filepath} onValueChange={select}>
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {(artifacts ?? []).map((artifactPath) => (
                      <SelectItem key={artifactPath} value={artifactPath}>
                        {getFileName(artifactPath)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {!isKnowledgePdf && previewable && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => setViewMode(value as "code" | "preview")}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {!isWriteFile && filepath.endsWith(".skill") && (
              <Tooltip content={t.toolCalls.skillInstallTooltip}>
                <ArtifactAction
                  icon={isInstalling ? LoaderIcon : PackageIcon}
                  label={t.common.install}
                  tooltip={t.common.install}
                  disabled={
                    isInstalling ||
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                  }
                  onClick={handleInstallSkill}
                />
              </Tooltip>
            )}
            {!isWriteFile && !isKnowledgeDoc && (
              <a href={urlOfArtifact({ filepath, threadId })} target="_blank" rel="noreferrer">
                <ArtifactAction
                  icon={SquareArrowOutUpRightIcon}
                  label={t.common.openInNewWindow}
                  tooltip={t.common.openInNewWindow}
                />
              </a>
            )}
            {isCodeFile && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!displayContent}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(displayContent ?? "");
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch (error) {
                    toast.error("Failed to copy to clipboard");
                    console.error(error);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isWriteFile && !isKnowledgeDoc && (
              <a
                href={urlOfArtifact({ filepath, threadId, download: true })}
                target="_blank"
                rel="noreferrer"
              >
                <ArtifactAction
                  icon={DownloadIcon}
                  label={t.common.download}
                  tooltip={t.common.download}
                />
              </a>
            )}
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={() => setOpen(false)}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent
        className={cn(
          "p-0",
          isKnowledgePdf &&
            knowledgePdfLocator?.filename &&
            (knowledgePdfLocator.pageNo ??
              knowledgePdfLocator.pdfPageNo ??
              knowledgePdfLocator.paragraphNo) &&
            "overflow-hidden",
        )}
      >
        {isKnowledgeDoc && knowledgeCitationMeta && (
          <KnowledgeCitationSummary
            originTitle={knowledgeCitationMeta.originTitle}
            sourceLabel={knowledgeCitationMeta.sourceLabel}
            sourceTitle={knowledgeCitationMeta.sourceTitle}
          />
        )}
        {isKnowledgePdf && knowledgePdfUrl && (
          knowledgePdfLocator?.filename &&
          (knowledgePdfLocator.pageNo ||
            knowledgePdfLocator.pdfPageNo ||
            knowledgePdfLocator.paragraphNo) ? (
            <KnowledgeCitationPdfViewer
              documentUrl={knowledgePdfUrl}
              pdfUrl={knowledgePdfUrl}
              pageNo={knowledgePdfLocator.pageNo}
              pdfPageNo={knowledgePdfLocator.pdfPageNo}
              paragraphNo={knowledgePdfLocator.paragraphNo}
              onCompareToggle={onKnowledgeCompareToggle}
            />
          ) : (
            <KnowledgeDocumentPdfViewer
              documentUrl={knowledgePdfUrl}
              pdfUrl={knowledgePdfUrl}
              initialPage={knowledgePdfPage ?? 0}
              filename={filepath}
              onCompareToggle={onKnowledgeCompareToggle}
            />
          )
        )}
        {!isKnowledgePdf && previewable && viewMode === "preview" && language === "markdown" && (
          <MarkdownDualPreview
            filepath={filepath}
            threadId={threadId}
            content={displayContent}
            highlightSnippet={knowledgeSnippet}
            mode={markdownPreviewVariant}
            onModeChange={setMarkdownPreviewVariant}
            rawUrl={isKnowledgeDoc ? knowledgeUrl ?? undefined : undefined}
          />
        )}
        {!isKnowledgePdf && previewable && viewMode === "preview" && language === "html" && (
          <div className="space-y-2 border-t border-border/30 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              原文预览
            </p>
            <iframe
              className="size-full min-h-[360px] w-full rounded-xl border"
              src={isKnowledgeDoc ? knowledgeUrl ?? undefined : urlOfArtifact({ filepath, threadId })}
            />
          </div>
        )}
        {!isKnowledgePdf && isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
          />
        )}
        {!isKnowledgeDoc && !isCodeFile && (
          isPdfFile ? (
            <PdfDualPreview
              filepath={filepath}
              threadId={threadId}
              convertedContent={convertedArtifactContent ?? ""}
            />
          ) : (
            <iframe
              className="size-full"
              src={urlOfArtifact({ filepath, threadId })}
            />
          )
        )}
      </ArtifactContent>
    </Artifact>
  );
}

type KnowledgeCitationState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeParagraphLocation };

function KnowledgePaneModeButtons({
  mode,
  onModeChange,
}: {
  mode: KnowledgeSidePaneMode | null;
  onModeChange: (mode: KnowledgeSidePaneMode | null) => void;
}) {
  return (
    <>
      <Button
        variant={mode === "compare" ? "default" : "outline"}
        size="sm"
        className="h-8"
        onClick={() => onModeChange(mode === "compare" ? null : "compare")}
      >
        原文对照
      </Button>
      <Button
        variant={mode === "translation" ? "default" : "outline"}
        size="sm"
        className="h-8"
        onClick={() => onModeChange(mode === "translation" ? null : "translation")}
      >
        <LanguagesIcon className="mr-1.5 size-4" />
        原文翻译
      </Button>
    </>
  );
}

function KnowledgeDocumentPdfViewer({
  documentUrl,
  pdfUrl,
  initialPage,
  filename,
  onCompareToggle,
}: {
  documentUrl: string;
  pdfUrl: string;
  initialPage: number;
  filename: string;
  onCompareToggle?: (open: boolean) => void;
}) {
  const [sidePaneMode, setSidePaneMode] = useState<KnowledgeSidePaneMode | null>(null);
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number>(initialPage + 1);
  const sidePaneOpen = sidePaneMode !== null;

  useEffect(() => {
    onCompareToggle?.(sidePaneOpen);
  }, [onCompareToggle, sidePaneOpen]);

  useEffect(() => {
    return () => {
      onCompareToggle?.(false);
    };
  }, [onCompareToggle]);

  return (
    <div
      className="grid size-full min-h-0"
      style={{
        gridTemplateColumns: sidePaneOpen
          ? `minmax(0, 1fr) ${KNOWLEDGE_SIDE_PANE_WIDTH}px`
          : "minmax(0, 1fr)",
      }}
    >
      <div className="min-w-0">
        <PdfViewer
          url={pdfUrl}
          initialPage={initialPage}
          className="size-full"
          onPageChange={(page) => setCurrentPdfPageNo(page + 1)}
          toolbarExtra={(
            <KnowledgePaneModeButtons
              mode={sidePaneMode}
              onModeChange={setSidePaneMode}
            />
          )}
        />
      </div>
      {sidePaneMode && (
        <KnowledgeSidePane
          documentUrl={documentUrl}
          currentPdfPageNo={currentPdfPageNo}
          originFilename={filename}
          originTitle={filename.replace(/\.pdf$/i, "")}
          mode={sidePaneMode}
        />
      )}
    </div>
  );
}

function KnowledgeCitationPdfViewer({
  documentUrl,
  pdfUrl,
  pageNo,
  pdfPageNo,
  paragraphNo,
  onCompareToggle,
}: {
  documentUrl: string;
  pdfUrl: string;
  pageNo: string | null;
  pdfPageNo: string | null;
  paragraphNo: string | null;
  onCompareToggle?: (open: boolean) => void;
}) {
  const [state, setState] = useState<KnowledgeCitationState>({ status: "loading" });
  const [numPages, setNumPages] = useState<number | null>(null);
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number | null>(null);
  const [pageInputValue, setPageInputValue] = useState<string>("");
  const [viewportSize, setViewportSize] = useState<{ width: number; height: number } | null>(null);
  const [imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [sidePaneMode, setSidePaneMode] = useState<KnowledgeSidePaneMode | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const sidePaneOpen = sidePaneMode !== null;

  useEffect(() => {
    onCompareToggle?.(sidePaneOpen);
  }, [onCompareToggle, sidePaneOpen]);

  useEffect(() => {
    return () => {
      onCompareToggle?.(false);
    };
  }, [onCompareToggle]);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    getKnowledgeParagraphLocationForDocumentUrl(documentUrl, { pageNo, pdfPageNo, paragraphNo })
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error.message || "定位信息加载失败",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, pageNo, pdfPageNo, paragraphNo]);

  useEffect(() => {
    let cancelled = false;
    let cleanup: (() => Promise<void>) | null = null;

    void (async () => {
      try {
        const { pdfjs } = await import("react-pdf");
        const loadingTask = pdfjs.getDocument(pdfUrl);
        cleanup = async () => {
          await loadingTask.destroy();
        };

        const document = await loadingTask.promise;
        if (!cancelled) {
          setNumPages(document.numPages);
        }
      } catch {
        if (!cancelled) {
          setNumPages(null);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (cleanup) {
        void cleanup();
      }
    };
  }, [pdfUrl]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const updateSize = () => {
      setViewportSize({
        width: viewport.clientWidth,
        height: viewport.clientHeight,
      });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(viewport);
    return () => {
      observer.disconnect();
    };
  }, [currentPdfPageNo]);

  useEffect(() => {
    if (state.status !== "ready") {
      setCurrentPdfPageNo(null);
      return;
    }
    setCurrentPdfPageNo(state.data.pdf_page_no ?? null);
  }, [state]);

  useEffect(() => {
    setImageNaturalSize(null);
  }, [currentPdfPageNo]);

  const totalPages =
    state.status === "ready" ? numPages ?? state.data.page_count ?? null : numPages;

  const goToPage = (page: number) => {
    if (page < 1) {
      return;
    }
    if (totalPages && page > totalPages) {
      return;
    }
    setCurrentPdfPageNo(page);
    setPageInputValue("");
  };

  const goToPrevPage = () => {
    if (!currentPdfPageNo || currentPdfPageNo <= 1) {
      return;
    }
    goToPage(currentPdfPageNo - 1);
  };

  const goToNextPage = () => {
    if (!currentPdfPageNo) {
      return;
    }
    if (totalPages && currentPdfPageNo >= totalPages) {
      return;
    }
    goToPage(currentPdfPageNo + 1);
  };

  if (state.status === "loading") {
    return (
      <div className="flex size-full items-center justify-center bg-muted/30 p-4 text-sm text-muted-foreground">
        正在加载 citation 定位...
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex size-full items-center justify-center bg-red-50 p-4 text-sm text-red-700">
        {state.message}
      </div>
    );
  }

  const { data } = state;
  const imageUrl = currentPdfPageNo
    ? buildKnowledgePageImageURLForDocumentUrl(documentUrl, currentPdfPageNo)
    : null;
  const isCitationPage = currentPdfPageNo === data.pdf_page_no;
  const pageWidth = data.page_meta?.page_width ?? null;
  const pageHeight = data.page_meta?.page_height ?? null;
  const displayWidth = imageNaturalSize?.width ?? pageWidth ?? null;
  const displayHeight = imageNaturalSize?.height ?? pageHeight ?? null;
  const bbox = data.bbox;
  const fittedScale =
    displayWidth && displayHeight && viewportSize
      ? Math.min(
          viewportSize.width / displayWidth,
          viewportSize.height / displayHeight,
          1,
        )
      : null;
  const renderedWidth =
    displayWidth && fittedScale ? Math.floor(displayWidth * fittedScale) : null;
  const renderedHeight =
    displayHeight && fittedScale ? Math.floor(displayHeight * fittedScale) : null;
  const overlayStyle =
    isCitationPage &&
    bbox &&
    pageWidth &&
    pageHeight &&
    renderedWidth &&
    renderedHeight
      ? {
          left: `${(bbox.x / pageWidth) * 100}%`,
          top: `${(bbox.y / pageHeight) * 100}%`,
          width: `${(bbox.width / pageWidth) * 100}%`,
          height: `${(bbox.height / pageHeight) * 100}%`,
        }
      : null;

  return (
    <div className="flex size-full flex-col overflow-hidden bg-muted/20">
      <div className="flex items-center justify-between border-b bg-muted/50 px-2 py-1.5">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={goToPrevPage}
            disabled={!currentPdfPageNo || currentPdfPageNo <= 1}
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
          <div className="flex items-center gap-1 text-sm">
            <Input
              type="text"
              className="h-7 w-12 text-center"
              value={
                pageInputValue !== ""
                  ? pageInputValue
                  : (currentPdfPageNo?.toString() ?? "")
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
              onFocus={() => {
                if (currentPdfPageNo) {
                  setPageInputValue(String(currentPdfPageNo));
                }
              }}
            />
            <span className="text-muted-foreground">/ {totalPages ?? "?"}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={goToNextPage}
            disabled={!currentPdfPageNo || (totalPages ? currentPdfPageNo >= totalPages : false)}
          >
            <ChevronRightIcon className="size-4" />
          </Button>
          <div className="ml-2 flex items-center gap-2">
            <KnowledgePaneModeButtons
              mode={sidePaneMode}
              onModeChange={setSidePaneMode}
            />
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          {isCitationPage && data.paragraph_no
            ? `引用段落：第 ${data.paragraph_no} 段`
            : "当前页预览"}
        </div>
      </div>
      <div
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: sidePaneOpen
            ? `minmax(0, 1fr) ${KNOWLEDGE_SIDE_PANE_WIDTH}px`
            : "minmax(0, 1fr)",
        }}
      >
        {imageUrl ? (
          <div
            className={cn(
              "flex min-h-0 min-w-0 p-4",
              sidePaneOpen ? "items-center justify-center pl-3 pr-2" : "items-center justify-center",
            )}
          >
            <div
              ref={viewportRef}
              className={cn(
                "flex h-full w-full overflow-hidden justify-center",
                sidePaneOpen ? "items-center" : "items-center",
              )}
            >
              <KnowledgePageSurface
                width={renderedWidth}
                height={renderedHeight}
              >
                <img
                  src={imageUrl}
                  alt={`${data.title} PDF page ${data.pdf_page_no ?? ""}`}
                  className="block bg-white object-contain"
                  style={
                    renderedWidth && renderedHeight
                      ? {
                          width: `${renderedWidth}px`,
                          height: `${renderedHeight}px`,
                        }
                      : undefined
                  }
                  onLoad={(event) => {
                    setImageNaturalSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    });
                  }}
                />
                {overlayStyle && (
                  <div
                    className="pointer-events-none absolute rounded-md border-2 border-emerald-500/90 bg-emerald-300/12"
                    style={overlayStyle}
                  />
                )}
              </KnowledgePageSurface>
            </div>
          </div>
        ) : (
          <div className="flex size-full items-center justify-center p-4 text-sm text-muted-foreground">
            当前 citation 缺少 PDF 页码，无法渲染整页预览。
          </div>
        )}
        {sidePaneMode && (
          <KnowledgeSidePane
            documentUrl={documentUrl}
            currentPdfPageNo={currentPdfPageNo}
            originFilename={data.filename}
            originTitle={data.title}
            mode={sidePaneMode}
            referencePageWidth={renderedWidth}
            referencePageHeight={renderedHeight}
          />
        )}
      </div>
    </div>
  );
}

function MarkdownDualPreview({
  filepath,
  threadId,
  content,
  highlightSnippet,
  mode,
  onModeChange,
  rawUrl,
}: {
  filepath: string;
  threadId: string;
  content: string;
  highlightSnippet?: string | null;
  mode: PreviewVariant;
  onModeChange: (mode: PreviewVariant) => void;
  rawUrl?: string;
}) {
  const iframeUrl = rawUrl ?? urlOfArtifact({ filepath, threadId });
  const showRendered = mode !== "original";
  const showOriginal = mode !== "rendered";
  const containerClass =
    mode === "split"
      ? "grid items-stretch gap-4 px-4 pb-4 md:grid-cols-2"
      : "px-4 pb-4";
  const panelClassName = "rounded-2xl border border-border/40 bg-muted p-4";

  return (
    <div className="space-y-3 border-t border-border/30">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4">
        <span className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          展示方式
        </span>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={mode}
          onValueChange={(value) => onModeChange(value as PreviewVariant)}
        >
          <ToggleGroupItem value="rendered">渲染视图</ToggleGroupItem>
          <ToggleGroupItem value="original">原文</ToggleGroupItem>
          <ToggleGroupItem value="split">双栏</ToggleGroupItem>
        </ToggleGroup>
        <a
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          href={iframeUrl}
          target="_blank"
          rel="noreferrer"
        >
          在新标签打开原文
        </a>
      </div>
      <div className={containerClass}>
        {showRendered && (
          <div className={cn(panelClassName, mode === "split" && "h-full")}>
            <HighlightedMarkdownPreview
              content={content ?? ""}
              highlightSnippet={highlightSnippet}
            />
          </div>
        )}
        {showOriginal && (
          <div className={cn("overflow-hidden rounded-2xl border border-border/40", mode === "split" && "h-full")}>
            <iframe
              className="h-full min-h-[360px] w-full bg-background"
              src={iframeUrl}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function KnowledgeCitationSummary({
  sourceLabel,
  sourceTitle,
  originTitle,
}: {
  sourceLabel: string | null;
  sourceTitle: string | null;
  originTitle: string | null;
}) {
  if ((!sourceLabel || sourceLabel === "知识库文档") && !originTitle) {
    return null;
  }

  return (
    <div className="border-b border-border/40 bg-amber-50/55 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-900/70">
        引用来源
      </p>
      {sourceLabel && (
        <p className="mt-1 text-sm text-stone-900">
          这条 citation 来自{sourceLabel}
          {sourceTitle ? `《${sourceTitle}》` : ""}
        </p>
      )}
      {originTitle && originTitle !== sourceTitle && (
        <p className="mt-1 text-xs text-stone-600">
          原始出处：{originTitle}
        </p>
      )}
    </div>
  );
}

function normalizeHighlightSnippet(snippet: string | null | undefined): string | null {
  if (!snippet) {
    return null;
  }
  const firstMeaningfulLine = snippet
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstMeaningfulLine) {
    return null;
  }
  return firstMeaningfulLine.slice(0, 120);
}

function clearHighlight(root: HTMLElement) {
  root.querySelectorAll("span[data-kb-highlight='true']").forEach((node) => {
    const parent = node.parentNode;
    if (!parent) {
      return;
    }
    while (node.firstChild) {
      parent.insertBefore(node.firstChild, node);
    }
    parent.removeChild(node);
    parent.normalize();
  });
}

function applyHighlight(root: HTMLElement, snippet: string): HTMLElement | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !node.textContent?.trim()) {
        return NodeFilter.FILTER_SKIP;
      }
      if (["SCRIPT", "STYLE"].includes(parent.tagName)) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const content = node.textContent ?? "";
    const index = content.indexOf(snippet);
    if (index === -1) {
      continue;
    }

    const startNode = node.splitText(index);
    const trailingNode = startNode.splitText(snippet.length);
    const highlight = document.createElement("span");
    highlight.dataset.kbHighlight = "true";
    highlight.className =
      "rounded-[3px] underline decoration-amber-500 decoration-2 underline-offset-4 bg-amber-100/70";
    startNode.parentNode?.insertBefore(highlight, trailingNode);
    highlight.appendChild(startNode);
    return highlight;
  }

  return null;
}

function HighlightedMarkdownPreview({
  content,
  highlightSnippet,
}: {
  content: string;
  highlightSnippet?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = containerRef.current;
    if (!root) {
      return;
    }

    clearHighlight(root);
    const snippet = normalizeHighlightSnippet(highlightSnippet);
    if (!snippet) {
      return;
    }

    const timeout = window.setTimeout(() => {
      const target = applyHighlight(root, snippet);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);

    return () => {
      window.clearTimeout(timeout);
      clearHighlight(root);
    };
  }, [content, highlightSnippet]);

  return (
    <div ref={containerRef}>
      <Streamdown
        className="size-full"
        {...streamdownPlugins}
        components={{ a: CitationLink }}
      >
        {content}
      </Streamdown>
    </div>
  );
}

function PdfDualPreview({
  filepath,
  threadId,
  convertedContent,
}: {
  filepath: string;
  threadId: string;
  convertedContent: string;
}) {
  const iframeUrl = urlOfArtifact({ filepath, threadId });
  const hasConverted = Boolean(convertedContent?.trim());
  const [mode, setMode] = useState<PreviewVariant>(
    hasConverted ? "split" : "original",
  );

  useEffect(() => {
    setMode(hasConverted ? "split" : "original");
  }, [filepath, hasConverted]);

  const showText = mode !== "original" && hasConverted;
  const showOriginal = mode !== "rendered";

  return (
    <div className="space-y-3 border-t border-border/30 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          PDF 预览
        </span>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={mode}
          onValueChange={(value) => setMode(value as PreviewVariant)}
        >
          {hasConverted && (
            <ToggleGroupItem value="rendered">转换文本</ToggleGroupItem>
          )}
          <ToggleGroupItem value="original">原始 PDF</ToggleGroupItem>
          {hasConverted && <ToggleGroupItem value="split">双栏</ToggleGroupItem>}
        </ToggleGroup>
        <a
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          href={iframeUrl}
          target="_blank"
          rel="noreferrer"
        >
          下载原文
        </a>
      </div>
      <div className={hasConverted && mode === "split" ? "grid md:grid-cols-2 gap-4" : ""}>
        {showText && hasConverted && (
          <div className="rounded-2xl border border-border/40 bg-muted p-4">
            <p className="text-xs font-medium text-muted-foreground">
              提取文本
            </p>
            <Streamdown
              className="size-full"
              {...streamdownPlugins}
              components={{ a: CitationLink }}
            >
              {convertedContent}
            </Streamdown>
          </div>
        )}
        {showOriginal && (
          <iframe
            className="w-full min-h-[420px] rounded-2xl border border-border/40"
            src={iframeUrl}
          />
        )}
      </div>
    </div>
  );
}
