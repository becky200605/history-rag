"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRightIcon, BookOpenIcon, ChevronRightIcon, ListTreeIcon, Loader2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { getKnowledgeBookOutline, resolveKnowledgeDocumentUrl, type KnowledgeBookOutlineEntry } from "@/core/knowledge/api";

import { KnowledgeCover } from "./knowledge-management-page.sections";
import { buildManagedFileOriginalHref, type ManagedKnowledgeFile } from "./knowledge-management-page.utils";

function OutlineRow({ entry, file }: { entry: KnowledgeBookOutlineEntry; file: ManagedKnowledgeFile }) {
  const href = entry.pdf_page_no ? buildManagedFileOriginalHref(file, entry.pdf_page_no) : null;
  const page = entry.book_page_no ?? entry.pdf_page_no;
  return (
    <span className="flex min-w-0 flex-1 items-start justify-between gap-3 text-sm leading-6">
      <span className="min-w-0 flex-1">{entry.title}</span>
      {page && (
        href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`在原文中打开${entry.title}，PDF 第 ${entry.pdf_page_no} 页`}
            className="inline-flex shrink-0 items-center gap-1 rounded text-xs leading-6 text-[#793b32] hover:underline"
          >
            第 {page} 页 <ArrowUpRightIcon className="size-3" />
          </a>
        ) : (
          <span className="shrink-0 text-xs leading-6 text-[#756859]">第 {page} 页</span>
        )
      )}
    </span>
  );
}

function BookOutline({ entries, file }: { entries: KnowledgeBookOutlineEntry[]; file: ManagedKnowledgeFile }) {
  const groups: { chapter: KnowledgeBookOutlineEntry; sections: KnowledgeBookOutlineEntry[] }[] = [];
  for (const entry of entries) {
    const group = groups.at(-1);
    if (!group || entry.level <= group.chapter.level) {
      groups.push({ chapter: entry, sections: [] });
    } else {
      group.sections.push(entry);
    }
  }

  return (
    <ul className="divide-y divide-[#eee6da] rounded-lg border border-[#e7ded1] bg-[#fffefa]">
      {groups.map(({ chapter, sections }, index) => (
        <li key={index} className="px-3.5 py-2.5">
          {sections.length === 0 ? (
            <div className="flex pl-[22px]"><OutlineRow entry={chapter} file={file} /></div>
          ) : (
            <details className="group">
              <summary className="flex cursor-pointer items-start gap-2 rounded text-[#3f3228] [&::-webkit-details-marker]:hidden">
                <ChevronRightIcon className="mt-[5px] size-3.5 shrink-0 text-[#9a7c53] transition-transform group-open:rotate-90" />
                <OutlineRow entry={chapter} file={file} />
              </summary>
              <ul className="mt-2 ml-[6px] space-y-2 border-l border-[#e7ded1] py-1 pl-4 text-[#675949]">
                {sections.map((section, sectionIndex) => (
                  <li key={sectionIndex} style={{ paddingLeft: Math.min(Math.max(section.level - chapter.level - 1, 0), 4) * 10 }}>
                    <OutlineRow entry={section} file={file} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}

export function KnowledgeBookDetails({
  file,
  onClose,
  restoreFocus,
}: {
  file: ManagedKnowledgeFile | null;
  onClose: () => void;
  restoreFocus: () => void;
}) {
  const resolved = file?.documentUrl ? resolveKnowledgeDocumentUrl(file.documentUrl) : null;
  const outlineFilename = resolved?.scope === "global" ? resolved.filename : null;
  const outline = useQuery({
    queryKey: ["knowledge", "book-outline", outlineFilename, file?.modified, file?.structuredFilename],
    queryFn: ({ signal }) => getKnowledgeBookOutline(outlineFilename!, signal),
    enabled: Boolean(outlineFilename),
    retry: false,
  });

  const originalHref = file ? buildManagedFileOriginalHref(file) : null;
  const summary = file?.summary?.trim();
  const format = file?.extension?.replace(/^\./, "").toUpperCase();
  const byline = [file?.author, file?.publisher, format].filter(Boolean).join(" · ");
  const tags = [...new Set(file?.keywords?.length ? file.keywords : file?.categories ?? [])].slice(0, 8);

  return (
    <Sheet open={Boolean(file)} onOpenChange={(open) => { if (!open) onClose(); }}>
      {file && (
        <SheetContent
          className="w-full gap-0 border-[#e9dfcf] bg-[#faf7ef] text-[#332820] sm:max-w-[600px]"
          onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus(); }}
        >
          <header className="flex shrink-0 items-start gap-4 border-b border-[#e8ded0] bg-[#fffdfa] px-5 pt-7 pb-6 pr-12 sm:gap-5 sm:px-7 sm:pr-12">
            <KnowledgeCover file={file} className="h-[104px] w-[72px]" />
            <div className="min-w-0 pt-1">
              <SheetTitle className="font-serif text-2xl leading-snug text-[#352820]">{file.title}</SheetTitle>
              <SheetDescription className="mt-2 text-[#746454]">{byline || (file.source === "global" ? "系统知识库" : "个人知识库")}</SheetDescription>
              {originalHref ? (
                <Button asChild size="sm" className="mt-3 bg-[#793b32] hover:bg-[#673027]">
                  <a href={originalHref} target="_blank" rel="noopener noreferrer"><BookOpenIcon /> 阅读原文 <ArrowUpRightIcon className="size-3.5" /></a>
                </Button>
              ) : <p className="mt-3 text-xs text-[#756859]">暂无原文</p>}
            </div>
          </header>

          <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-5 py-6 sm:px-7">
            <section aria-labelledby="knowledge-summary-heading">
              <h2 id="knowledge-summary-heading" className="mb-3 font-serif text-lg font-semibold">内容摘要</h2>
              {summary ? (
                <p className="text-sm leading-7 break-words whitespace-pre-wrap text-[#56483b]">{summary}</p>
              ) : (
                <p className="text-sm text-[#756859]">暂无摘要</p>
              )}
              {tags.length > 0 && (
                <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="主题">
                  {tags.map((tag) => <li key={tag} className="rounded border border-[#e7dbc8] bg-[#f3ebde] px-2 py-0.5 text-xs text-[#735638]">{tag}</li>)}
                </ul>
              )}
            </section>

            <section aria-labelledby="knowledge-outline-heading">
              <h2 id="knowledge-outline-heading" className="mb-3 flex items-center gap-2 font-serif text-lg font-semibold">
                <ListTreeIcon className="size-[18px] text-[#8c704a]" /> 书内目录
              </h2>
              {outline.isLoading ? (
                <p role="status" className="flex items-center gap-2 text-sm text-[#756859]"><Loader2Icon className="size-4 animate-spin" /> 正在读取目录</p>
              ) : outline.isError ? (
                <div className="flex flex-wrap items-center gap-2 text-sm text-[#756859]">
                  书内目录加载失败
                  <Button type="button" variant="link" size="sm" onClick={() => void outline.refetch()}>重试</Button>
                </div>
              ) : outline.data?.length ? (
                <BookOutline entries={outline.data} file={file} />
              ) : (
                <p className="text-sm text-[#756859]">暂无可识别的书内目录</p>
              )}
            </section>

            {file.folderDisplay && (
              <p className="border-t border-[#e8ded0] pt-4 text-xs leading-5 text-[#756859]">馆藏位置 · {file.folderDisplay}</p>
            )}
          </div>
        </SheetContent>
      )}
    </Sheet>
  );
}
