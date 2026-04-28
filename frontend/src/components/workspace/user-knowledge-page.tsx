"use client";

import {
  ChevronDownIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FolderIcon,
  Loader2Icon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  buildFolderBreadcrumbs,
  buildScopedFolderTree,
  findFolderNode,
  getFolderDisplayName,
  normalizeFolderPath,
  type FolderTreeNode,
} from "@/components/workspace/knowledge-management-page.utils";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { buildKnowledgeDocumentUrl } from "@/core/knowledge/api";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useCreateUserDerivedKnowledge,
  useDeleteUserKnowledgeRecord,
  useUpdateUserKnowledgeRecordContent,
  useUserKnowledgeRecordContent,
  useUserKnowledgeRecords,
  useUserKnowledgeSpaces,
} from "@/core/knowledge/user-hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function formatTime(value?: string | null) {
  if (!value) {
    return "未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatListDate(value?: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleDateString("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
}

function stripFileExtension(value: string) {
  return value.replace(/\.[^.]+$/, "");
}

function getReadableRecordTitle(record: UserKnowledgeRecord) {
  const displayTitle = record.display_title?.trim();
  const title = record.title?.trim();
  const readableTitle =
    displayTitle && displayTitle.length > 0 ? displayTitle : title;
  if (readableTitle) {
    return readableTitle;
  }
  const sourceName = record.origin_filename ?? record.filename;
  if (sourceName) {
    return stripFileExtension(sourceName);
  }
  return "未命名";
}

function isNoteRecord(record: UserKnowledgeRecord) {
  return !["upload", "import_ref"].includes(record.source_kind);
}

function getOriginAnchorNumber(
  record: UserKnowledgeRecord,
  key: "page_no" | "pdf_page_no" | "paragraph_no",
) {
  const value = record.origin_anchor?.[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
}

function buildOriginalJumpHref(
  record: UserKnowledgeRecord,
  recordId: string,
  knowledgeSpaceId?: string | null,
) {
  if (!record.origin_filename) {
    return null;
  }
  if (record.origin_scope !== "global" && record.origin_scope !== "user") {
    return null;
  }

  const pageNo = getOriginAnchorNumber(record, "page_no");
  const pdfPageNo = getOriginAnchorNumber(record, "pdf_page_no");
  const paragraphNo = getOriginAnchorNumber(record, "paragraph_no");
  if (!pageNo && !pdfPageNo && !paragraphNo) {
    return null;
  }

  const params = new URLSearchParams({
    filename: record.origin_filename,
    scope: record.origin_scope,
    document_url: buildKnowledgeDocumentUrl(
      record.origin_scope,
      record.origin_filename,
    ),
    back_href: `/workspace/notes?space=${encodeURIComponent(knowledgeSpaceId ?? record.knowledge_space_id ?? "")}&record=${encodeURIComponent(recordId)}`,
    back_label: "笔记",
  });
  if (pageNo) {
    params.set("page_no", String(pageNo));
  }
  if (pdfPageNo) {
    params.set("pdf_page_no", String(pdfPageNo));
  }
  if (paragraphNo) {
    params.set("paragraph_no", String(paragraphNo));
  }
  return `/workspace/knowledge/view?${params.toString()}`;
}

function sortRecords(records: UserKnowledgeRecord[]) {
  return [...records].sort((left, right) => {
    const leftTime = new Date(
      left.updated_at ?? left.created_at ?? 0,
    ).getTime();
    const rightTime = new Date(
      right.updated_at ?? right.created_at ?? 0,
    ).getTime();
    return rightTime - leftTime;
  });
}

function SidebarRecordRow({
  record,
  isActive,
  onClick,
}: {
  record: UserKnowledgeRecord;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group border-accent/10 relative flex min-h-[5.5rem] w-full min-w-0 flex-col justify-center gap-2 border-b px-6 py-4 text-left transition-all",
        isActive
          ? "bg-primary/5 text-primary"
          : "text-stone-600 hover:bg-stone-50/50 hover:text-stone-900",
      )}
    >
      <div
        className={cn(
          "bg-primary absolute top-0 bottom-0 left-0 w-1 transition-all",
          isActive ? "opacity-100" : "opacity-0 group-hover:opacity-40",
        )}
      />

      <span className="line-clamp-3 block min-w-0 flex-1 font-serif text-[15px] leading-[1.6] font-medium">
        {getReadableRecordTitle(record)}
      </span>
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-[11px] text-stone-400">
          {normalizeFolderPath(record.folder_path)}
        </span>
        <span className="shrink-0 font-sans text-[10px] tracking-widest uppercase opacity-30">
          {formatListDate(record.updated_at ?? record.created_at)}
        </span>
      </div>
    </button>
  );
}

function SidebarFolderNode({
  node,
  selectedFolderPath,
  onSelect,
  depth = 0,
}: {
  node: FolderTreeNode;
  selectedFolderPath: string;
  onSelect: (path: string) => void;
  depth?: number;
}) {
  const isSelected = selectedFolderPath === node.path;

  return (
    <div>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-all",
          isSelected
            ? "bg-primary/8 text-primary"
            : "text-stone-600 hover:bg-stone-100 hover:text-stone-900",
        )}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
      >
        <FolderIcon className="size-4 shrink-0 opacity-70" />
        <span className="min-w-0 flex-1 truncate">
          {getFolderDisplayName(node.name)}
        </span>
        <span className="text-[10px] opacity-45">{node.fileCount}</span>
      </button>
      {node.children.length > 0 ? (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <SidebarFolderNode
              key={child.path}
              node={child}
              selectedFolderPath={selectedFolderPath}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ReadonlyRecordState({ record }: { record: UserKnowledgeRecord }) {
  return (
    <div className="border-y border-slate-200 py-4 text-slate-700">
      <div className="text-sm leading-7 text-slate-500">
        {record.source_kind === "import_ref"
          ? "这是收藏映射，当前不直接编辑正文。去原文页面摘录或批注后，会在这里形成可编辑文档。"
          : "这个条目当前不支持直接编辑正文。"}
      </div>
      <div className="mt-5 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-3">
          <span className="text-slate-500">来源</span>
          <span className="text-right text-slate-900">
            {record.origin_filename ?? record.filename ?? "未知"}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-3">
          <span className="text-slate-500">更新时间</span>
          <span className="text-right text-slate-900">
            {formatTime(record.updated_at)}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function NotesPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [selectedFolderPath, setSelectedFolderPath] = useState("all");
  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [draftRecordId, setDraftRecordId] = useState<string | null>(null);
  const [isExcerptOpen, setIsExcerptOpen] = useState(false);
  const [titleInputWidth, setTitleInputWidth] = useState<number>(320);
  const titleMeasureRef = useRef<HTMLSpanElement | null>(null);
  const selectedSpaceIdFromQuery = searchParams.get("space");

  useEffect(() => {
    const nextWidth = titleMeasureRef.current?.offsetWidth;
    if (!nextWidth) {
      return;
    }
    setTitleInputWidth(Math.max(240, Math.min(nextWidth + 12, 860)));
  }, [titleDraft]);

  const spacesQuery = useUserKnowledgeSpaces();
  const personalSpaces = useMemo(
    () =>
      (spacesQuery.data?.spaces ?? []).filter(
        (space) => space.type === "personal",
      ),
    [spacesQuery.data?.spaces],
  );
  const activeSpaceId = useMemo(() => {
    if (
      selectedSpaceIdFromQuery &&
      personalSpaces.some((space) => space.id === selectedSpaceIdFromQuery)
    ) {
      return selectedSpaceIdFromQuery;
    }
    return (
      personalSpaces.find((space) => space.is_default)?.id ??
      personalSpaces[0]?.id ??
      null
    );
  }, [personalSpaces, selectedSpaceIdFromQuery]);

  const { data, isLoading, error } = useUserKnowledgeRecords(activeSpaceId);
  const createMutation = useCreateUserDerivedKnowledge();
  const deleteMutation = useDeleteUserKnowledgeRecord();
  const updateMutation = useUpdateUserKnowledgeRecordContent();

  const records = useMemo(
    () => sortRecords((data?.records ?? []).filter(isNoteRecord)),
    [data?.records],
  );
  const personalFolderPaths = useMemo(
    () => data?.folders ?? [],
    [data?.folders],
  );
  const folderTree = useMemo(
    () =>
      buildScopedFolderTree({
        filePaths: records.map((record) =>
          normalizeFolderPath(record.folder_path),
        ),
        explicitPaths: personalFolderPaths,
        prefix: "personal:",
        source: "personal",
      }),
    [personalFolderPaths, records],
  );
  const selectedFolderNode = useMemo(
    () => findFolderNode(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const selectedLogicalFolderPath = useMemo(() => {
    if (selectedFolderPath.startsWith("personal:")) {
      return selectedFolderPath.slice("personal:".length);
    }
    return "";
  }, [selectedFolderPath]);
  const folderBreadcrumbs = useMemo(
    () => buildFolderBreadcrumbs(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const visibleRecords = useMemo(() => {
    if (
      selectedFolderPath === "all" ||
      selectedFolderPath === "personal-root"
    ) {
      return records;
    }
    return records.filter((record) => {
      const recordFolderPath = `personal:${normalizeFolderPath(record.folder_path)}`;
      return (
        recordFolderPath === selectedFolderPath ||
        recordFolderPath.startsWith(`${selectedFolderPath}/`)
      );
    });
  }, [records, selectedFolderPath]);
  const requestedRecordId = searchParams.get("record");

  useEffect(() => {
    document.title = "笔记 - 财政历史智能知识库";
  }, []);

  useEffect(() => {
    if (!activeSpaceId || selectedSpaceIdFromQuery === activeSpaceId) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set("space", activeSpaceId);
    router.replace(`${pathname}?${params.toString()}`);
  }, [activeSpaceId, pathname, router, searchParams, selectedSpaceIdFromQuery]);

  useEffect(() => {
    if (selectedFolderPath !== "all") {
      const availablePaths = new Set<string>();
      const collect = (nodes: FolderTreeNode[]) => {
        for (const node of nodes) {
          availablePaths.add(node.path);
          collect(node.children);
        }
      };
      collect(folderTree);
      if (!availablePaths.has(selectedFolderPath)) {
        setSelectedFolderPath("all");
      }
    }
  }, [folderTree, selectedFolderPath]);

  useEffect(() => {
    if (visibleRecords.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && visibleRecords.some((record) => record.id === current)
        ? current
        : (visibleRecords[0]?.id ?? null),
    );
  }, [visibleRecords]);

  useEffect(() => {
    if (!requestedRecordId) {
      return;
    }
    const requestedRecord = visibleRecords.find(
      (record) => record.id === requestedRecordId,
    );
    if (!requestedRecord) {
      return;
    }
    setSelectedRecordId(requestedRecordId);
  }, [requestedRecordId, visibleRecords]);

  const selectedRecord =
    visibleRecords.find((record) => record.id === selectedRecordId) ??
    visibleRecords[0] ??
    null;

  const contentQuery = useUserKnowledgeRecordContent(
    selectedRecord?.id ?? null,
  );

  useEffect(() => {
    if (!contentQuery.data || !selectedRecord?.id) {
      return;
    }
    setDraftRecordId(selectedRecord.id);
    setTitleDraft(contentQuery.data.title);
    setContentDraft(contentQuery.data.editable_content);
    setIsExcerptOpen(false);
  }, [contentQuery.data, selectedRecord?.id]);

  const isDraftDirty = useMemo(() => {
    if (!contentQuery.data || draftRecordId !== selectedRecord?.id) {
      return false;
    }
    return (
      titleDraft !== contentQuery.data.title ||
      contentDraft !== contentQuery.data.editable_content
    );
  }, [
    contentDraft,
    contentQuery.data,
    draftRecordId,
    selectedRecord?.id,
    titleDraft,
  ]);

  const handleDelete = async (recordId: string) => {
    setDeletingRecordId(recordId);
    try {
      await deleteMutation.mutateAsync(recordId);
      toast.success("已删除");
    } catch (deleteError) {
      toast.error((deleteError as Error).message ?? "删除失败");
    } finally {
      setDeletingRecordId(null);
    }
  };

  const handleCreateNote = async () => {
    if (!activeSpaceId) {
      toast.error("当前没有可用的个人知识库文件夹");
      return;
    }
    try {
      const created = await createMutation.mutateAsync({
        title: "未命名笔记",
        content: "",
        sourceKind: "note",
        knowledgeSpaceId: activeSpaceId,
        folderPath: selectedLogicalFolderPath || null,
      });
      setSelectedRecordId(created.record.id);
      toast.success("已新建笔记");
    } catch (createError) {
      toast.error((createError as Error).message ?? "新建笔记失败");
    }
  };

  const handleSave = async () => {
    if (!selectedRecord?.id || !contentQuery.data?.editable) {
      return;
    }
    try {
      await updateMutation.mutateAsync({
        recordId: selectedRecord.id,
        title: titleDraft,
        content: contentDraft,
      });
      toast.success("已保存");
    } catch (saveError) {
      toast.error((saveError as Error).message ?? "保存失败");
    }
  };

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody className="items-center justify-center px-6 py-10">
          <div className="text-muted-foreground text-sm">
            当前为静态模式，笔记功能不可用。
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  const selectedIsDeleting =
    deleteMutation.isPending && deletingRecordId === selectedRecord?.id;
  const hasLockedExcerpt = Boolean(
    contentQuery.data?.mode === "derived" && contentQuery.data.locked_excerpt,
  );
  const originalJumpHref = selectedRecord
    ? buildOriginalJumpHref(selectedRecord, selectedRecord.id, activeSpaceId)
    : null;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader className="border-primary/5 border-b" />
      <WorkspaceBody className="min-h-0 overflow-hidden bg-white">
        <div className="flex h-full min-h-0 w-full overflow-hidden bg-transparent">
          <aside className="border-accent/20 flex min-h-0 w-full shrink-0 flex-col border-b bg-white lg:w-[280px] lg:border-r lg:border-b-0">
            <div className="p-4">
              <Button
                size="sm"
                variant="outline"
                className="border-primary/30 bg-primary/5 text-primary hover:bg-primary group h-11 w-full justify-start gap-3 rounded-none font-serif transition-all hover:text-white"
                disabled={createMutation.isPending}
                onClick={() => void handleCreateNote()}
              >
                {createMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <PlusIcon className="size-4 transition-transform group-hover:rotate-90" />
                )}
                <span className="tracking-widest">
                  起卷{" "}
                  {selectedLogicalFolderPath
                    ? `· ${selectedLogicalFolderPath}`
                    : ""}
                </span>
              </Button>
            </div>

            <div className="border-accent/10 border-y px-4 py-2 font-sans text-[10px] tracking-[0.2em] text-stone-400 uppercase">
              目录结构
            </div>
            <ScrollArea className="border-accent/10 max-h-[240px] border-b">
              <div className="p-3">
                <button
                  type="button"
                  onClick={() => setSelectedFolderPath("all")}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-all",
                    selectedFolderPath === "all"
                      ? "bg-primary/8 text-primary"
                      : "text-stone-600 hover:bg-stone-100 hover:text-stone-900",
                  )}
                >
                  <FolderIcon className="size-4 shrink-0 opacity-70" />
                  <span className="flex-1">全部笔记</span>
                  <span className="text-[10px] opacity-45">
                    {records.length}
                  </span>
                </button>
                <div className="mt-1">
                  {folderTree.map((node) => (
                    <SidebarFolderNode
                      key={node.path}
                      node={node}
                      selectedFolderPath={selectedFolderPath}
                      onSelect={setSelectedFolderPath}
                    />
                  ))}
                </div>
              </div>
            </ScrollArea>

            <div className="border-accent/10 border-b px-4 py-3">
              <div className="font-sans text-[10px] tracking-[0.2em] text-stone-400 uppercase">
                当前目录
              </div>
              <div className="mt-2 min-h-[22px] text-sm text-stone-700">
                {selectedFolderPath === "all"
                  ? "全部笔记"
                  : folderBreadcrumbs.length > 0
                    ? folderBreadcrumbs
                        .map((crumb) => getFolderDisplayName(crumb.name))
                        .join(" / ")
                    : getFolderDisplayName(
                        selectedFolderNode?.name ?? "未分类",
                      )}
              </div>
            </div>

            <div className="border-accent/10 border-b px-4 py-2 font-sans text-[10px] tracking-[0.2em] text-stone-400 uppercase">
              目次 · {visibleRecords.length} 卷
            </div>

            <ScrollArea className="min-h-0 flex-1">
              {isLoading ? (
                <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2Icon className="size-4 animate-spin" />
                  正在加载
                </div>
              ) : error ? (
                <div className="m-4 border border-red-500/20 bg-red-500/6 p-4 text-sm text-red-600">
                  {error.message}
                </div>
              ) : visibleRecords.length === 0 ? (
                <div className="p-4 text-sm text-slate-500">
                  当前目录下暂无笔记。
                </div>
              ) : (
                <div>
                  {visibleRecords.map((record) => (
                    <SidebarRecordRow
                      key={record.id}
                      record={record}
                      isActive={selectedRecord?.id === record.id}
                      onClick={() => setSelectedRecordId(record.id)}
                    />
                  ))}
                </div>
              )}
            </ScrollArea>
          </aside>

          <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
            <div className="border-accent/20 border-b px-6 py-4 shadow-sm">
              <div className="flex items-start gap-6">
                <div className="max-w-full min-w-0">
                  {selectedRecord ? (
                    <div className="space-y-1.5">
                      <div className="relative inline-flex max-w-full items-center gap-2 align-middle">
                        <Input
                          value={titleDraft}
                          onChange={(event) =>
                            setTitleDraft(event.target.value)
                          }
                          disabled={!contentQuery.data?.editable}
                          className="text-primary h-auto !w-auto max-w-[860px] min-w-[240px] rounded-none border-0 bg-transparent px-0 py-0 font-serif text-2xl font-bold shadow-none focus-visible:ring-0 disabled:opacity-100"
                          style={{ width: `${titleInputWidth}px` }}
                        />
                        <span
                          ref={titleMeasureRef}
                          aria-hidden="true"
                          className="pointer-events-none invisible absolute top-0 left-0 px-0 font-serif text-2xl font-bold whitespace-pre"
                        >
                          {titleDraft || "未命名笔记"}
                        </span>
                        {hasLockedExcerpt ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="text-accent hover:bg-accent/10 h-8 shrink-0 rounded-md px-2"
                            onClick={() =>
                              setIsExcerptOpen((current) => !current)
                            }
                          >
                            <ChevronDownIcon
                              className={cn(
                                "size-4 transition-transform",
                                isExcerptOpen && "rotate-180",
                              )}
                            />
                          </Button>
                        ) : null}
                      </div>
                      {selectedRecord ? (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
                          <span className="flex items-center gap-1.5">
                            <span className="opacity-60">目录：</span>
                            <span>
                              {normalizeFolderPath(selectedRecord.folder_path)}
                            </span>
                          </span>
                          {selectedRecord.origin_filename ? (
                            <span className="flex items-center gap-1.5 transition-colors hover:text-stone-700">
                              <span className="opacity-60">来源：</span>
                              <span className="font-medium">
                                {selectedRecord.origin_filename}
                              </span>
                            </span>
                          ) : null}
                          {contentQuery.data?.location_label ? (
                            <span className="opacity-60">
                              {contentQuery.data.location_label}
                            </span>
                          ) : null}
                          {originalJumpHref ? (
                            <Link
                              href={originalJumpHref}
                              className="text-accent hover:text-accent/80 inline-flex items-center gap-1 font-medium transition-all hover:translate-x-0.5"
                            >
                              跳转原文
                              <ExternalLinkIcon className="size-3.5" />
                            </Link>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="ml-auto flex items-center gap-4">
                  {selectedRecord ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 rounded-full p-0 text-stone-300 transition-all hover:rotate-12 hover:bg-red-50 hover:text-red-500"
                      disabled={deleteMutation.isPending}
                      onClick={() => void handleDelete(selectedRecord.id)}
                      title="废弃此卷 (删除)"
                    >
                      {selectedIsDeleting ? (
                        <Loader2Icon className="size-4 animate-spin" />
                      ) : (
                        <Trash2Icon className="size-4" />
                      )}
                    </Button>
                  ) : null}
                </div>
              </div>
              {hasLockedExcerpt && isExcerptOpen ? (
                <div className="border-accent/10 mt-4 border-t pt-4">
                  <div className="font-serif text-[15px] leading-relaxed whitespace-pre-wrap text-stone-500 italic">
                    {contentQuery.data?.locked_excerpt}
                  </div>
                </div>
              ) : null}
            </div>

            {!selectedRecord ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    选择左侧笔记查看或编辑
                  </div>
                </div>
              </div>
            ) : contentQuery.isLoading ? (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 text-stone-400">
                <div className="relative">
                  <Loader2Icon className="text-primary/20 size-8 animate-spin" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="bg-primary size-1 animate-pulse rounded-full" />
                  </div>
                </div>
                <div className="font-serif tracking-widest italic">
                  正在开启卷宗...
                </div>
              </div>
            ) : contentQuery.error ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-10">
                <div className="w-full max-w-[920px] border border-red-500/20 bg-red-500/6 p-6 text-sm text-red-600">
                  {contentQuery.error.message}
                </div>
              </div>
            ) : (
              <div className="relative flex min-h-0 flex-1 flex-col">
                <ScrollArea className="min-h-0 flex-1">
                  <div className="w-full px-6 py-6 md:px-10">
                    <div className="pt-4 pb-32">
                      {contentQuery.data?.editable ? (
                        <Textarea
                          value={contentDraft}
                          onChange={(event) =>
                            setContentDraft(event.target.value)
                          }
                          placeholder={
                            contentQuery.data.mode === "derived"
                              ? "在这里继续写你的摘抄、理解或批注。"
                              : "输入正文内容"
                          }
                          className="selection:bg-primary/10 min-h-[600px] w-full resize-none rounded-none border-0 bg-transparent px-0 py-2 font-serif text-[18px] leading-[2.2] text-stone-800 placeholder:text-stone-300 focus-visible:ring-0"
                        />
                      ) : (
                        <ReadonlyRecordState record={selectedRecord} />
                      )}
                    </div>
                  </div>
                </ScrollArea>

                {contentQuery.data?.editable && (
                  <button
                    type="button"
                    disabled={updateMutation.isPending || !isDraftDirty}
                    onClick={() => void handleSave()}
                    className={cn(
                      "absolute right-10 bottom-10 z-30 flex size-20 flex-col items-center justify-center transition-all",
                      updateMutation.isPending || !isDraftDirty
                        ? "cursor-not-allowed opacity-30 grayscale"
                        : "cursor-pointer opacity-100 hover:scale-110 active:scale-95",
                    )}
                  >
                    <div className="relative flex size-full items-center justify-center">
                      <div className="bg-primary absolute inset-0 shadow-lg" />
                      <div className="relative z-10 flex size-[85%] flex-col items-center justify-center border-2 border-white/40 font-serif text-white">
                        <span className="text-2xl leading-none font-bold">
                          {updateMutation.isPending ? "载" : "印"}
                        </span>
                        <span className="mt-0.5 text-[10px] font-medium tracking-tighter opacity-80">
                          {updateMutation.isPending ? "记录中" : "封卷保存"}
                        </span>
                      </div>
                      {/* Decorative corner accent */}
                      <div className="absolute -top-1 -left-1 size-3 border-t-2 border-l-2 border-white/20" />
                    </div>
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
