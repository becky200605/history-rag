"use client";

import { useMemo } from "react";
import type { ComponentProps } from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";

import { CitationLink } from "../citations/citation-link";

const CITATION_LINK_PATTERN = /\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]+)\)/gi;

function extractCitationHref(citation: string): string | null {
  const match = /^\[citation:[^\]]+\]\((<[^>\n]+>|[^)\n]+)\)$/i.exec(citation.trim());
  if (!match) {
    return null;
  }
  const rawHref = match[1]?.trim() ?? "";
  if (!rawHref) {
    return null;
  }
  if (rawHref.startsWith("<") && rawHref.endsWith(">")) {
    const unwrappedHref = rawHref.slice(1, -1).trim();
    return unwrappedHref || null;
  }
  return rawHref;
}

function normalizeInternalCitationHref(href: string | null): string | null {
  if (!href) return null;
  if (
    href.startsWith("/api/knowledge/docs/") ||
    href.startsWith("/api/secure-knowledge/users/me/knowledge/docs/")
  ) {
    return encodeURI(href).replace(/%253A/g, "%3A");
  }
  return href;
}

function isDisplayableCitationHref(href: string | null): boolean {
  const normalizedHref = normalizeInternalCitationHref(href);
  if (!normalizedHref || /\s/.test(normalizedHref) || /^citations?:/i.test(normalizedHref)) {
    return false;
  }
  try {
    const url = normalizedHref.startsWith("/")
      ? new URL(normalizedHref, window.location.origin)
      : new URL(normalizedHref);
    if (normalizedHref.startsWith("/")) {
      return Boolean(url.pathname);
    }
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function stripInvalidCitations(content: string): string {
  return content.replace(CITATION_LINK_PATTERN, (citation) => {
    const href = extractCitationHref(citation);
    const normalizedHref = normalizeInternalCitationHref(href);
    if (!isDisplayableCitationHref(normalizedHref)) {
      return "";
    }
    if (!href || !normalizedHref || href === normalizedHref) {
      return citation;
    }
    const wrappedHref = citation.includes("(<") ? `<${normalizedHref}>` : normalizedHref;
    return citation.replace(/\((<[^>\n]+>|[^)\n]+)\)$/i, `(${wrappedHref})`);
  });
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
};

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
}: MarkdownContentProps) {
  const components = useMemo(() => {
    return {
      a: (props: ComponentProps<"a">) => {
        const normalizedHref =
          typeof props.href === "string"
            ? normalizeInternalCitationHref(props.href)
            : null;
        if (
          typeof props.children === "string" &&
          /^citation:/i.test(props.children) &&
          !isDisplayableCitationHref(normalizedHref)
        ) {
          return null;
        }
        if (typeof props.children === "string") {
          const match = /^citation:(.+)$/.exec(props.children);
          if (match) {
            const [, text] = match;
            return <CitationLink {...props} href={normalizedHref ?? props.href}>{text}</CitationLink>;
          }
        }
        return <a {...props} href={normalizedHref ?? props.href} />;
      },
      ...componentsFromProps,
    };
  }, [componentsFromProps]);

  if (!content) return null;
  const sanitizedContent = stripInvalidCitations(content);
  if (!sanitizedContent.trim()) return null;

  return (
    <MessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {sanitizedContent}
    </MessageResponse>
  );
}
