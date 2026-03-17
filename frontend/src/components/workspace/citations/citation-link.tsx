 "use client";

import { ExternalLinkIcon, FileTextIcon } from "lucide-react";
import { useMemo, type ComponentProps, type MouseEvent } from "react";

import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useArtifacts } from "@/components/workspace/artifacts";
import { cn } from "@/lib/utils";

interface KnowledgeDocInfo {
  filename: string;
  isPdf: boolean;
  page: number | null;
}

function parseKnowledgeDocUrl(url: string): KnowledgeDocInfo | null {
  if (!url.startsWith("/api/knowledge/docs/")) return null;
  
  try {
    const urlObj = new URL(url, window.location.origin);
    const pathParts = urlObj.pathname.split("/");
    const filename = decodeURIComponent(pathParts[pathParts.length - 1] || "");
    const isPdf = filename.toLowerCase().endsWith(".pdf");
    const pageStr = urlObj.searchParams.get("page");
    const page = pageStr ? parseInt(pageStr, 10) : null;
    
    return {
      filename,
      isPdf,
      page: isNaN(page as number) ? null : page,
    };
  } catch {
    return null;
  }
}

export function CitationLink({
  href,
  children,
  ...props
}: ComponentProps<"a">) {
  const domain = extractDomain(href ?? "");
  const { select, setOpen } = useArtifacts();

  const knowledgeDocInfo = useMemo(
    () => (href ? parseKnowledgeDocUrl(href) : null),
    [href],
  );
  const isKnowledgeDoc = knowledgeDocInfo !== null;

  // Priority: children > domain
  const childrenText =
    typeof children === "string"
      ? children.replace(/^citation:\s*/i, "")
      : null;
  const isGenericText = childrenText === "Source" || childrenText === "来源";
  const displayText = (!isGenericText && childrenText) ?? domain;

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!href) {
      event.stopPropagation();
      return;
    }

    // Local knowledge-base documents: open in right-side viewer
    if (isKnowledgeDoc) {
      event.preventDefault();
      event.stopPropagation();
      select(`knowledge-doc:${href}`);
      setOpen(true);
      return;
    }

    // Other links: keep default behavior (new tab)
    event.stopPropagation();
  };

  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
        <a
          href={href}
          target={isKnowledgeDoc ? undefined : "_blank"}
          rel={isKnowledgeDoc ? undefined : "noopener noreferrer"}
          className="inline-flex items-center"
          onClick={handleClick}
          {...props}
        >
          <Badge
            variant="secondary"
            className="hover:bg-secondary/80 mx-0.5 cursor-pointer gap-1 rounded-full px-2 py-0.5 text-xs font-normal"
          >
            {knowledgeDocInfo?.isPdf ? (
              <FileTextIcon className="size-3" />
            ) : null}
            {displayText}
            {knowledgeDocInfo?.isPdf && knowledgeDocInfo.page !== null && (
              <span className="text-muted-foreground">
                (第{knowledgeDocInfo.page + 1}页)
              </span>
            )}
            {!isKnowledgeDoc && <ExternalLinkIcon className="size-3" />}
          </Badge>
        </a>
      </HoverCardTrigger>
      <HoverCardContent className={cn("relative w-80 p-0", props.className)}>
        <div className="p-3">
          <div className="space-y-1">
            {displayText && (
              <h4 className="truncate font-medium text-sm leading-tight">
                {displayText}
              </h4>
            )}
            {knowledgeDocInfo && (
              <div className="text-muted-foreground text-xs">
                <p className="truncate">{knowledgeDocInfo.filename}</p>
                {knowledgeDocInfo.isPdf && knowledgeDocInfo.page !== null && (
                  <p>第 {knowledgeDocInfo.page + 1} 页</p>
                )}
              </div>
            )}
            {!isKnowledgeDoc && href && (
              <p className="truncate break-all text-muted-foreground text-xs">
                {href}
              </p>
            )}
          </div>
          {!isKnowledgeDoc && href && (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary mt-2 inline-flex items-center gap-1 text-xs hover:underline"
            >
              Visit source
              <ExternalLinkIcon className="size-3" />
            </a>
          )}
          {isKnowledgeDoc && (
            <p className="text-muted-foreground mt-2 text-xs">
              点击在侧边栏中查看
            </p>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

function extractDomain(url: string): string {
  if (!url) return "";
  // Relative URL (e.g. /api/knowledge/docs/xxx.md?page=1) → show short label
  if (url.startsWith("/")) {
    try {
      const urlObj = new URL(url, window.location.origin);
      const match = /\/api\/knowledge\/docs\/(.+)$/.exec(urlObj.pathname);
      if (match) {
        return decodeURIComponent(match[1] ?? "知识库文档");
      }
      return "知识库文档";
    } catch {
      const match = /\/api\/knowledge\/docs\/([^?]+)/.exec(url);
      return match ? decodeURIComponent(match[1] ?? "知识库文档") : "知识库文档";
    }
  }
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}
