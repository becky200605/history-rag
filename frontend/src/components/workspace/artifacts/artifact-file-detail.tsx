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
  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);
  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile]);
  const fileBaseName = useMemo(() => {
    const name = getFileName(filepath);
    return name.replace(/\.[^.]+$/, "");
  }, [filepath]);
  const matchingMdArtifact = useMemo(() => {
    if (!artifacts?.length) {
      return null;
    }
    const targetName = `${fileBaseName}.md`.toLowerCase();
    return artifacts.find(
      (artifactPath) =>
        getFileName(artifactPath).toLowerCase() === targetName,
    ) ?? null;
  }, [artifacts, fileBaseName]);
  const {
    content: convertedArtifactContent,
  } = useArtifactContent({
    threadId,
    filepath: matchingMdArtifact ?? "",
    enabled: Boolean(matchingMdArtifact),
  });
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
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
  }, [filepath, isWriteFile, isSkillFile]);
  const previewable = useMemo(() => {
    return (language === "html" && !isWriteFile) || language === "markdown";
  }, [isWriteFile, language]);
  const { content } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile,
  });

  const displayContent = content ?? "";
  const extension = useMemo(() => getFileExtension(filepath), [filepath]);
  const isPdfFile = extension === "pdf";
  const [markdownPreviewVariant, setMarkdownPreviewVariant] =
    useState<PreviewVariant>("split");

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
          {previewable && (
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
            {!isWriteFile && (
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
            {!isWriteFile && (
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
        {previewable && viewMode === "preview" && language === "markdown" && (
          <MarkdownDualPreview
            filepath={filepath}
            threadId={threadId}
            content={displayContent}
            mode={markdownPreviewVariant}
            onModeChange={(value) =>
              setMarkdownPreviewVariant(value as PreviewVariant)
            }
          />
        )}
        {previewable && viewMode === "preview" && language === "html" && (
          <div className="space-y-2 border-t border-border/30 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              原文预览
            </p>
            <iframe
              className="size-full min-h-[360px] w-full rounded-xl border"
              src={urlOfArtifact({ filepath, threadId })}
            />
          </div>
        )}
        {isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
          />
        )}
        {!isCodeFile && (
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
}: {
  filepath: string;
  threadId: string;
  content: string;
  mode: PreviewVariant;
  onModeChange: (mode: PreviewVariant) => void;
}) {
  const iframeUrl = urlOfArtifact({ filepath, threadId });
  const showRendered = mode !== "original";
  const showOriginal = mode !== "rendered";
  const containerClass = mode === "split" ? "grid md:grid-cols-2 gap-4 px-4 pb-4" : "px-4 pb-4";

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
          {hasConverted && <ToggleGroupItem value="rendered">转换文本</ToggleGroupItem>}
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
      <div
        className={
          hasConverted && mode === "split"
            ? "grid md:grid-cols-2 gap-4"
            : ""
        }
      >
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
