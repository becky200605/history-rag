export interface KnowledgeCitationMeta {
  scope: string | null;
  sourceKind: string | null;
  sourceLabel: string | null;
  sourceTitle: string | null;
  originTitle: string | null;
}

function fallbackSourceLabel(scope: string | null, sourceKind: string | null): string | null {
  if (scope === "user") {
    if (sourceKind && ["excerpt", "annotation", "translation", "note"].includes(sourceKind)) {
      return "你的笔记";
    }
    if (sourceKind === "upload") {
      return "你上传的文档";
    }
    return "你的文档";
  }

  if (scope === "thread") {
    return "你上传的文档";
  }

  if (scope === "global") {
    return "知识库文档";
  }

  return null;
}

export function getKnowledgeCitationMeta(documentUrl: string): KnowledgeCitationMeta {
  try {
    const base =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost:2026";
    const url = new URL(documentUrl, base);
    const scope = url.searchParams.get("citation_scope");
    const sourceKind = url.searchParams.get("citation_source_kind");
    return {
      scope,
      sourceKind,
      sourceLabel:
        url.searchParams.get("citation_source_label") ??
        fallbackSourceLabel(scope, sourceKind),
      sourceTitle: url.searchParams.get("citation_source_title"),
      originTitle: url.searchParams.get("citation_origin_title"),
    };
  } catch {
    return {
      scope: null,
      sourceKind: null,
      sourceLabel: null,
      sourceTitle: null,
      originTitle: null,
    };
  }
}
