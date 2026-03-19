import { ExternalLinkIcon } from "lucide-react";
import type { ComponentProps } from "react";
import { usePathname } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

export function CitationLink({ 
  href, 
  children,
  ...props 
}: ComponentProps<"a">) {
  const pathname = usePathname();
  const safeHref = normalizeCitationHref(href);
  const viewerHref = buildKnowledgeCitationViewerHref(safeHref, pathname);
  const finalHref = viewerHref ?? safeHref;
  const domain = extractDomain(safeHref ?? "");
  
  // Priority: children > domain
  const childrenText =
    typeof children === "string"
      ? children.replace(/^citation:\s*/i, "")
      : null;
  const isGenericText = childrenText === "Source" || childrenText === "来源";
  const displayText = (!isGenericText && childrenText) ?? domain;

  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
          <a
          href={finalHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center"
          onClick={(e) => e.stopPropagation()}
          {...props}
        >
          <Badge
            variant="secondary"
            className="hover:bg-secondary/80 mx-0.5 cursor-pointer gap-1 rounded-full px-2 py-0.5 text-xs font-normal"
          >
            {displayText}
            <ExternalLinkIcon className="size-3" />
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
            {href && (
              <p className="truncate break-all text-muted-foreground text-xs">
                {finalHref}
              </p>
            )}
          </div>
          <a
            href={finalHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary mt-2 inline-flex items-center gap-1 text-xs hover:underline"
          >
            Visit source
            <ExternalLinkIcon className="size-3" />
          </a>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

function normalizeCitationHref(url: string | undefined): string | undefined {
  if (!url) {
    return url;
  }
  try {
    return encodeURI(decodeURI(url));
  } catch {
    try {
      return encodeURI(url);
    } catch {
      return url;
    }
  }
}

function buildKnowledgeCitationViewerHref(
  url: string | undefined,
  pathname: string | null,
): string | undefined {
  if (!url) {
    return undefined;
  }
  try {
    const parsed = new URL(url, typeof window !== "undefined" ? window.location.origin : "http://localhost:2026");
    if (!parsed.pathname.startsWith("/api/knowledge/docs/") || !parsed.pathname.toLowerCase().endsWith(".pdf")) {
      return undefined;
    }

    const filename = decodeURIComponent(parsed.pathname.replace("/api/knowledge/docs/", ""));
    const params = new URLSearchParams();
    params.set("filename", filename);
    const pageNo = parsed.searchParams.get("page_no");
    const pdfPageNo = parsed.searchParams.get("pdf_page_no");
    const paragraphNo = parsed.searchParams.get("paragraph_no");
    if (pageNo) {
      params.set("page_no", pageNo);
    }
    if (pdfPageNo) {
      params.set("pdf_page_no", pdfPageNo);
    }
    if (paragraphNo) {
      params.set("paragraph_no", paragraphNo);
    }
    const threadId = extractThreadId(pathname);
    if (threadId) {
      params.set("thread_id", threadId);
    }
    params.set("source_url", parsed.pathname + parsed.search + parsed.hash);
    params.set("original_url", parsed.pathname + parsed.search + parsed.hash);
    return `/workspace/knowledge/view?${params.toString()}`;
  } catch {
    return undefined;
  }
}

function extractThreadId(pathname: string | null): string | null {
  if (!pathname) {
    return null;
  }
  const match = pathname.match(/^\/workspace\/chats\/([^/?#]+)/);
  return match?.[1] ?? null;
}
