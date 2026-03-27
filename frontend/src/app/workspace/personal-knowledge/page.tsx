"use client";

import {
  BookOpenIcon,
  ExternalLinkIcon,
  FileTextIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useDeleteUserKnowledgeRecord,
  useUpdateUserKnowledgeRecordContent,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecordContent,
  useUserKnowledgeRecords,
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

function formatTimelineLabel(value?: string | null) {
  if (!value) {
    return "最近";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "最近";
  }
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const diffDays = diff / (1000 * 60 * 60 * 24);
  if (diffDays < 1) {
    return "今天";
  }
  if (diffDays < 2) {
    return "昨天";
  }
  if (diffDays < 7) {
    return new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(date);
  }
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function statusLabel(status?: string | null) {
  switch (status) {
    case "uploaded":
      return "已上传";
    case "parsed":
      return "已解析";
    case "indexed":
      return "已入库";
    case "failed":
      return "失败";
    case "imported":
      return "已收藏";
    case "queued":
    case "queued_ocr":
    case "queued_embedding":
      return "排队中";
    case "parsing":
      return "解析中";
    case "indexing":
      return "入库中";
    default:
      return status ?? "未知";
  }
}

function getRecordTitle(record: UserKnowledgeRecord) {
  return record.display_title ?? record.title ?? record.filename ?? "未命名资料";
}

function getRecordKindLabel(record: UserKnowledgeRecord) {
  switch (record.source_kind) {
    case "import_ref":
      return "收藏";
    case "excerpt":
      return "摘录";
    case "annotation":
      return "批注";
    case "translation":
      return "翻译";
    case "note":
      return "笔记";
    default:
      return "文档";
  }
}

function getRecordSecondaryText(record: UserKnowledgeRecord) {
  return record.origin_filename ?? record.filename ?? "无来源信息";
}

function isWithinDays(value?: string | null, days = 7) {
  if (!value) {
    return false;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  return Date.now() - date.getTime() <= days * 24 * 60 * 60 * 1000;
}

function sortRecords(records: UserKnowledgeRecord[]) {
  return [...records].sort((left, right) => {
    const leftTime = new Date(left.updated_at ?? left.created_at ?? 0).getTime();
    const rightTime = new Date(right.updated_at ?? right.created_at ?? 0).getTime();
    return rightTime - leftTime;
  });
}

function SidebarRecordCard({
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
        "w-full rounded-2xl border px-4 py-3 text-left transition",
        isActive
          ? "border-emerald-500/50 bg-[#243127] text-stone-50"
          : "border-white/6 bg-[#1f1f1f] text-stone-200 hover:border-white/12 hover:bg-[#262626]",
      )}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-stone-500">
        <span>{formatTimelineLabel(record.updated_at ?? record.created_at)}</span>
        <span>{getRecordKindLabel(record)}</span>
      </div>
      <div className="mt-2 line-clamp-2 text-[15px] font-semibold leading-6">
        {getRecordTitle(record)}
      </div>
      <div className="mt-2 line-clamp-2 text-sm leading-6 text-stone-400">
        {getRecordSecondaryText(record)}
      </div>
    </button>
  );
}

function ReadonlyRecordState({
  record,
}: {
  record: UserKnowledgeRecord;
}) {
  return (
    <div className="rounded-3xl border border-white/8 bg-[#1d1d1d] p-6 text-stone-300">
      <div className="text-sm leading-7 text-stone-400">
        {record.source_kind === "import_ref"
          ? "这是收藏映射，当前不直接编辑正文。去原文页面摘录或批注后，会在这里形成可编辑文档。"
          : "这个条目当前不支持直接编辑正文。"}
      </div>
      <div className="mt-6 space-y-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/6 pb-3">
          <span className="text-stone-500">来源</span>
          <span className="text-right text-stone-200">
            {record.origin_filename ?? record.filename ?? "未知"}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/6 pb-3">
          <span className="text-stone-500">状态</span>
          <span className="text-right text-stone-200">{statusLabel(record.parse_status)}</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-stone-500">更新时间</span>
          <span className="text-right text-stone-200">{formatTime(record.updated_at)}</span>
        </div>
      </div>
    </div>
  );
}

export default function PersonalKnowledgePage() {
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [draftRecordId, setDraftRecordId] = useState<string | null>(null);

  const { data, isLoading, error, refetch, isFetching } = useUserKnowledgeRecords();
  const uploadMutation = useUploadUserKnowledgeFiles();
  const deleteMutation = useDeleteUserKnowledgeRecord();
  const updateMutation = useUpdateUserKnowledgeRecordContent();

  const records = useMemo(() => sortRecords(data?.records ?? []), [data?.records]);
  const requestedRecordId = searchParams.get("record");

  const filteredRecords = useMemo(() => {
    if (!searchText.trim()) {
      return records;
    }
    const query = searchText.trim().toLowerCase();
    return records.filter((record) => {
      const haystack = [
        getRecordTitle(record),
        record.origin_filename,
        record.filename,
        record.source_kind,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [records, searchText]);

  useEffect(() => {
    document.title = "个人知识库 - 财政历史大模型";
  }, []);

  useEffect(() => {
    if (filteredRecords.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && filteredRecords.some((record) => record.id === current)
        ? current
        : filteredRecords[0]?.id ?? null,
    );
  }, [filteredRecords]);

  useEffect(() => {
    if (!requestedRecordId) {
      return;
    }
    if (!records.some((record) => record.id === requestedRecordId)) {
      return;
    }
    setSelectedRecordId(requestedRecordId);
  }, [records, requestedRecordId]);

  const selectedRecord =
    filteredRecords.find((record) => record.id === selectedRecordId) ?? filteredRecords[0] ?? null;

  const contentQuery = useUserKnowledgeRecordContent(selectedRecord?.id ?? null);

  useEffect(() => {
    if (!contentQuery.data || !selectedRecord?.id) {
      return;
    }
    setDraftRecordId(selectedRecord.id);
    setTitleDraft(contentQuery.data.title);
    setContentDraft(contentQuery.data.editable_content);
  }, [contentQuery.data, selectedRecord?.id]);

  const recentRecords = useMemo(
    () => filteredRecords.filter((record) => isWithinDays(record.updated_at ?? record.created_at)),
    [filteredRecords],
  );
  const olderRecords = useMemo(
    () => filteredRecords.filter((record) => !isWithinDays(record.updated_at ?? record.created_at)),
    [filteredRecords],
  );

  const isDraftDirty = useMemo(() => {
    if (!contentQuery.data || draftRecordId !== selectedRecord?.id) {
      return false;
    }
    return (
      titleDraft !== contentQuery.data.title ||
      contentDraft !== contentQuery.data.editable_content
    );
  }, [contentDraft, contentQuery.data, draftRecordId, selectedRecord?.id, titleDraft]);

  const handleUpload = async () => {
    if (pendingFiles.length === 0) {
      toast.error("请选择要上传的文件");
      return;
    }
    try {
      await uploadMutation.mutateAsync({ files: pendingFiles });
      toast.success(`已提交 ${pendingFiles.length} 个文件`);
      setPendingFiles([]);
      setIsUploadDialogOpen(false);
    } catch (uploadError) {
      toast.error((uploadError as Error).message ?? "上传失败");
    }
  };

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
          <div className="text-sm text-muted-foreground">
            当前为静态模式，个人知识库功能不可用。
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  const selectedIsDeleting =
    deleteMutation.isPending && deletingRecordId === selectedRecord?.id;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="min-h-0 overflow-hidden bg-[#101010] px-3 py-3 md:px-4 md:py-4">
        <div className="mx-auto flex h-full min-h-0 w-full max-w-[1600px] overflow-hidden rounded-[28px] border border-white/8 bg-[#171717] shadow-[0_24px_80px_-36px_rgba(0,0,0,0.6)]">
          <aside className="flex min-h-0 w-full shrink-0 flex-col border-b border-white/8 bg-[#141414] lg:w-[330px] lg:border-b-0 lg:border-r">
            <div className="border-b border-white/8 px-5 pb-4 pt-5">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-stone-100">
                  <BookOpenIcon className="size-4" />
                  <span className="text-sm font-semibold">个人知识库</span>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9 rounded-xl text-stone-400 hover:bg-white/6 hover:text-stone-100"
                  onClick={() => setIsUploadDialogOpen(true)}
                >
                  <PlusIcon className="size-4" />
                </Button>
              </div>

              <div className="mt-4 relative">
                <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-500" />
                <Input
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="搜索标题或来源"
                  className="h-10 rounded-xl border-white/8 bg-[#1e1e1e] pl-10 text-stone-100 placeholder:text-stone-500"
                />
              </div>

              <div className="mt-4 text-xs text-stone-500">
                共 {data?.count ?? 0} 条，已入库 {data?.doc_count ?? 0} 条
              </div>
            </div>

            <ScrollArea className="min-h-0 flex-1 px-3 py-4">
              {isLoading ? (
                <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-stone-500">
                  <Loader2Icon className="size-4 animate-spin" />
                  正在加载
                </div>
              ) : error ? (
                <div className="rounded-2xl border border-red-500/20 bg-red-500/8 p-4 text-sm text-red-300">
                  {error.message}
                </div>
              ) : filteredRecords.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 bg-[#1c1c1c] p-5 text-sm text-stone-500">
                  当前没有匹配的内容。
                </div>
              ) : (
                <div className="space-y-5">
                  {recentRecords.length > 0 ? (
                    <div className="space-y-3">
                      <div className="px-1 text-xs uppercase tracking-[0.18em] text-stone-500">过去 7 天</div>
                      {recentRecords.map((record) => (
                        <SidebarRecordCard
                          key={record.id}
                          record={record}
                          isActive={selectedRecord?.id === record.id}
                          onClick={() => setSelectedRecordId(record.id)}
                        />
                      ))}
                    </div>
                  ) : null}
                  {olderRecords.length > 0 ? (
                    <div className="space-y-3">
                      <div className="px-1 text-xs uppercase tracking-[0.18em] text-stone-500">更早</div>
                      {olderRecords.map((record) => (
                        <SidebarRecordCard
                          key={record.id}
                          record={record}
                          isActive={selectedRecord?.id === record.id}
                          onClick={() => setSelectedRecordId(record.id)}
                        />
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </ScrollArea>
          </aside>

          <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#1a1a1a]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3 md:px-6">
              <div className="flex items-center gap-3 text-sm text-stone-400">
                <span>{selectedRecord ? getRecordKindLabel(selectedRecord) : "未选择"}</span>
                {selectedRecord ? <span>{statusLabel(selectedRecord.parse_status)}</span> : null}
                {contentQuery.data?.editable ? (
                  <span>{isDraftDirty ? "有未保存修改" : "已同步"}</span>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-xl text-stone-300 hover:bg-white/6 hover:text-white"
                  onClick={() => void refetch()}
                  disabled={isFetching}
                >
                  <RefreshCwIcon className={cn("size-4", isFetching && "animate-spin")} />
                  刷新
                </Button>
                {selectedRecord?.artifact_url ? (
                  <a
                    href={selectedRecord.artifact_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/8 bg-[#232323] px-3 text-sm text-stone-200 transition hover:border-white/14 hover:bg-[#292929]"
                  >
                    <ExternalLinkIcon className="size-4" />
                    打开原文
                  </a>
                ) : null}
                {contentQuery.data?.editable ? (
                  <Button
                    size="sm"
                    className="h-9 rounded-xl bg-emerald-600 px-4 text-white hover:bg-emerald-500"
                    disabled={updateMutation.isPending || !isDraftDirty}
                    onClick={() => void handleSave()}
                  >
                    {updateMutation.isPending ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : null}
                    保存
                  </Button>
                ) : null}
                {selectedRecord ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 rounded-xl text-stone-300 hover:bg-white/6 hover:text-white"
                    disabled={deleteMutation.isPending}
                    onClick={() => void handleDelete(selectedRecord.id)}
                  >
                    {selectedIsDeleting ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <Trash2Icon className="size-4" />
                    )}
                    删除
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  className="h-9 rounded-xl bg-white px-4 text-stone-950 hover:bg-stone-200"
                  onClick={() => setIsUploadDialogOpen(true)}
                  disabled={uploadMutation.isPending}
                >
                  {uploadMutation.isPending ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <UploadIcon className="size-4" />
                  )}
                  上传
                </Button>
              </div>
            </div>

            <ScrollArea className="min-h-0 flex-1">
              {!selectedRecord ? (
                <div className="flex min-h-full items-center justify-center px-6 py-16">
                  <div className="max-w-md text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#232323] text-stone-100">
                      <FileTextIcon className="size-6" />
                    </div>
                    <div className="mt-5 text-xl font-semibold text-stone-100">还没有可查看的内容</div>
                    <div className="mt-3 text-sm leading-7 text-stone-500">
                      上传文档，或者从原文里创建摘录和批注。
                    </div>
                  </div>
                </div>
              ) : contentQuery.isLoading ? (
                <div className="flex min-h-full items-center justify-center gap-2 text-sm text-stone-500">
                  <Loader2Icon className="size-4 animate-spin" />
                  正在载入正文
                </div>
              ) : contentQuery.error ? (
                <div className="mx-auto max-w-[920px] px-6 py-10">
                  <div className="rounded-3xl border border-red-500/20 bg-red-500/8 p-6 text-sm text-red-300">
                    {contentQuery.error.message}
                  </div>
                </div>
              ) : (
                <div className="mx-auto w-full max-w-[920px] px-6 py-8 md:px-10 md:py-10">
                  <Input
                    value={titleDraft}
                    onChange={(event) => setTitleDraft(event.target.value)}
                    disabled={!contentQuery.data?.editable}
                    className="h-auto border-none bg-transparent px-0 py-0 text-4xl font-semibold tracking-tight text-stone-100 shadow-none focus-visible:ring-0 disabled:opacity-100 md:text-[42px]"
                  />

                  <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-sm text-stone-500">
                    <span>{getRecordKindLabel(selectedRecord)}</span>
                    <span>{statusLabel(selectedRecord.parse_status)}</span>
                    <span>更新于 {formatTime(selectedRecord.updated_at)}</span>
                    {(contentQuery.data?.origin_filename ?? selectedRecord.origin_filename) ? (
                      <span>
                        来源 {contentQuery.data?.origin_filename ?? selectedRecord.origin_filename}
                      </span>
                    ) : null}
                    {contentQuery.data?.location_label ? (
                      <span>{contentQuery.data.location_label}</span>
                    ) : null}
                  </div>

                  {contentQuery.data?.mode === "derived" ? (
                    <div className="mt-8 rounded-3xl border border-emerald-500/18 bg-[#152018] p-6">
                      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.16em] text-emerald-300/80">
                        <span>锁定原文</span>
                        <span>不可修改</span>
                      </div>
                      <div className="mt-4 whitespace-pre-wrap text-[16px] leading-8 text-stone-100">
                        {contentQuery.data.locked_excerpt || "原文段落缺失"}
                      </div>
                    </div>
                  ) : null}

                  <div className="mt-8">
                    {contentQuery.data?.editable ? (
                      <Textarea
                        value={contentDraft}
                        onChange={(event) => setContentDraft(event.target.value)}
                        placeholder={
                          contentQuery.data.mode === "derived"
                            ? "在这里继续写你的摘抄、理解或批注。"
                            : "输入正文内容"
                        }
                        className="min-h-[520px] resize-none rounded-[28px] border-white/8 bg-[#141414] px-6 py-5 text-[16px] leading-8 text-stone-100 placeholder:text-stone-500 focus-visible:border-emerald-500/40 focus-visible:ring-emerald-500/15"
                      />
                    ) : (
                      <ReadonlyRecordState record={selectedRecord} />
                    )}
                  </div>
                </div>
              )}
            </ScrollArea>
          </section>
        </div>

        <Dialog open={isUploadDialogOpen} onOpenChange={setIsUploadDialogOpen}>
          <DialogContent className="sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>上传到个人知识库</DialogTitle>
              <DialogDescription>
                支持 PDF、Office、Markdown 和 TXT，上传后会进入个人长期检索范围。
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  setPendingFiles(files);
                }}
              />
              <Button
                variant="outline"
                className="w-full border-dashed"
                onClick={() => fileInputRef.current?.click()}
              >
                选择文件
              </Button>
              <div className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-stone-600">
                {pendingFiles.length === 0
                  ? "尚未选择文件"
                  : `已选择 ${pendingFiles.length} 个文件：${pendingFiles.map((file) => file.name).join("，")}`}
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setPendingFiles([]);
                  setIsUploadDialogOpen(false);
                }}
                disabled={uploadMutation.isPending}
              >
                取消
              </Button>
              <Button
                className="bg-stone-900 text-white hover:bg-stone-800"
                onClick={() => void handleUpload()}
                disabled={uploadMutation.isPending || pendingFiles.length === 0}
              >
                {uploadMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <UploadIcon className="size-4" />
                )}
                开始上传
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
