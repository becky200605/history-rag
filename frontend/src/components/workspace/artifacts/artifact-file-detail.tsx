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
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";
import { PdfViewer } from "./pdf-viewer";

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
      if (!pageStr) return null;
      const page = parseInt(pageStr, 10);
      return isNaN(page) ? null : page;
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
      return url.pathname;
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
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    // Treat .skill files as markdown (they contain SKILL.md)
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

  const [knowledgeContent, setKnowledgeContent] = useState<string | null>(null);
  const [isKnowledgeLoading, setIsKnowledgeLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<Error | null>(null);

  useEffect(() => {
    // Skip loading for PDF files - they are rendered by PdfViewer
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
    const marker = "\n<a id=\"kb-snippet\"></a>";
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
    // 等待 Streamdown 渲染完成后滚动到锚点
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

  const displayContent = isKnowledgeDoc
    ? highlightedKnowledgeContent ?? ""
    : content ?? "";

  const [viewMode, setViewMode] = useState<"code" | "preview">("code");
  const [isInstalling, setIsInstalling] = useState(false);

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
            {isWriteFile ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select value={filepath} onValueChange={select}>
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {(artifacts ?? []).map((filepath) => (
                      <SelectItem key={filepath} value={filepath}>
                        {getFileName(filepath)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {/* Hide view mode toggle for PDFs */}
          {!isKnowledgePdf && previewable && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) =>
                setViewMode(value as "code" | "preview")
              }
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
              <a href={urlOfArtifact({ filepath, threadId })} target="_blank">
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
                disabled={!content}
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
        {/* PDF Viewer for knowledge base PDFs */}
        {isKnowledgePdf && knowledgePdfUrl && (
          <PdfViewer
            url={knowledgePdfUrl}
            initialPage={knowledgePdfPage ?? 0}
            className="size-full"
          />
        )}
        {/* Markdown/HTML preview */}
        {!isKnowledgePdf &&
          previewable &&
          viewMode === "preview" &&
          (language === "markdown" || language === "html") && (
            <ArtifactFilePreview
              filepath={filepath}
              threadId={threadId}
              content={displayContent}
              language={language ?? "text"}
            />
          )}
        {/* Code editor for source view */}
        {!isKnowledgePdf && isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
          />
        )}
        {/* Iframe for other file types */}
        {!isKnowledgePdf && !isCodeFile && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath, threadId })}
          />
        )}
      </ArtifactContent>
    </Artifact>
  );
}

export function ArtifactFilePreview({
  filepath,
  threadId,
  content,
  language,
}: {
  filepath: string;
  threadId: string;
  content: string;
  language: string;
}) {
  if (language === "markdown") {
    return (
      <div className="size-full px-4">
        <Streamdown
          className="size-full"
          {...streamdownPlugins}
          components={{ a: CitationLink }}
        >
          {content ?? ""}
        </Streamdown>
      </div>
    );
  }
  if (language === "html") {
    return (
      <iframe
        className="size-full"
        src={urlOfArtifact({ filepath, threadId })}
      />
    );
  }
  return null;
}

