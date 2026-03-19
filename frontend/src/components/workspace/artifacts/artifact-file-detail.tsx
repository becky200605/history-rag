import {
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  SquareArrowOutUpRightIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { installSkill } from "@/core/skills/api";
import { streamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileExtension, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";
import { PdfViewer } from "./pdf-viewer";

type PreviewVariant = "rendered" | "original" | "split";

export function ArtifactFileDetail({
  className,
  filepath: filepathFromProps,
  threadId,
}: {
  className?: string;
  filepath: string;
  threadId: string;
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

  const highlightedKnowledgeContent = useMemo(() => {
    if (!isKnowledgeDoc || !knowledgeContent || !knowledgeSnippet) {
      return knowledgeContent;
    }
    const index = knowledgeContent.indexOf(knowledgeSnippet);
    if (index === -1) {
      return knowledgeContent;
    }
    const marker = '\n<a id="kb-snippet"></a>';
    return (
      knowledgeContent.slice(0, index) +
      marker +
      knowledgeContent.slice(index)
    );
  }, [isKnowledgeDoc, knowledgeContent, knowledgeSnippet]);

  useEffect(() => {
    if (!isKnowledgeDoc || !highlightedKnowledgeContent) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const el = document.getElementById("kb-snippet");
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 200);
    return () => {
      window.clearTimeout(timeout);
    };
  }, [isKnowledgeDoc, highlightedKnowledgeContent]);

  const displayContent = useMemo(() => {
    if (isKnowledgeDoc) {
      if (knowledgeError) {
        return knowledgeError.message;
      }
      if (isKnowledgeLoading) {
        return "Loading knowledge document...";
      }
      return highlightedKnowledgeContent ?? "";
    }
    return content ?? "";
  }, [
    content,
    highlightedKnowledgeContent,
    isKnowledgeDoc,
    isKnowledgeLoading,
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
      <ArtifactContent className="p-0">
        {isKnowledgePdf && knowledgePdfUrl && (
          <PdfViewer
            url={knowledgePdfUrl}
            initialPage={knowledgePdfPage ?? 0}
            className="size-full"
          />
        )}
        {!isKnowledgePdf && previewable && viewMode === "preview" && language === "markdown" && (
          <MarkdownDualPreview
            filepath={filepath}
            threadId={threadId}
            content={displayContent}
            mode={markdownPreviewVariant}
            onModeChange={(value) => setMarkdownPreviewVariant(value as PreviewVariant)}
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

function MarkdownDualPreview({
  filepath,
  threadId,
  content,
  mode,
  onModeChange,
  rawUrl,
}: {
  filepath: string;
  threadId: string;
  content: string;
  mode: PreviewVariant;
  onModeChange: (mode: PreviewVariant) => void;
  rawUrl?: string;
}) {
  const iframeUrl = rawUrl ?? urlOfArtifact({ filepath, threadId });
  const showRendered = mode !== "original";
  const showOriginal = mode !== "rendered";
  const containerClass =
    mode === "split" ? "grid md:grid-cols-2 gap-4 px-4 pb-4" : "px-4 pb-4";

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
          <div className="rounded-2xl border border-border/40 bg-muted p-4">
            <Streamdown
              className="size-full"
              {...streamdownPlugins}
              components={{ a: CitationLink }}
            >
              {content ?? ""}
            </Streamdown>
          </div>
        )}
        {showOriginal && (
          <iframe
            className="w-full min-h-[360px] rounded-2xl border border-border/40"
            src={iframeUrl}
          />
        )}
      </div>
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
