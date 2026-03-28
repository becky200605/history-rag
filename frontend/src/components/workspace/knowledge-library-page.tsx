"use client";

import {
  FileTextIcon,
  Loader2Icon,
  PlusIcon,
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  KnowledgeStructuredViewer,
} from "@/components/workspace/artifacts/knowledge-structured-viewer";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { buildKnowledgeDocumentUrl } from "@/core/knowledge/api";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useDeleteUserKnowledgeRecord,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecords,
} from "@/core/knowledge/user-hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

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

function getRecordTitle(record: UserKnowledgeRecord) {
  return record.filename ?? record.origin_filename ?? record.display_title ?? record.title ?? "未命名";
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

function resolveRecordDocumentUrl(
  record: UserKnowledgeRecord,
  options?: { preferPreview?: boolean },
) {
  if (options?.preferPreview) {
    if (record.preview_artifact_url) {
      return record.preview_artifact_url;
    }
    if (record.preview_filename) {
      return buildKnowledgeDocumentUrl("user", record.preview_filename);
    }
  }
  if (record.artifact_url) {
    return record.artifact_url;
  }
  if (record.origin_scope === "global" && record.origin_filename) {
    return buildKnowledgeDocumentUrl("global", record.origin_filename);
  }
  if (record.origin_scope === "user" && record.origin_filename) {
    return buildKnowledgeDocumentUrl("user", record.origin_filename);
  }
  return null;
}

function isPdfRecord(record: UserKnowledgeRecord) {
  const filename = record.filename ?? record.origin_filename ?? "";
  return filename.toLowerCase().endsWith(".pdf");
}

function isReferenceRecord(record: UserKnowledgeRecord) {
  return ["upload", "import_ref"].includes(record.source_kind);
}

function sortRecords(records: UserKnowledgeRecord[]) {
  return [...records].sort((left, right) => {
    const leftTime = new Date(left.updated_at ?? left.created_at ?? 0).getTime();
    const rightTime = new Date(right.updated_at ?? right.created_at ?? 0).getTime();
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
        "grid h-10 w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-l-2 px-4 text-left transition",
        isActive
          ? "border-l-[rgb(57,130,152)] bg-slate-50 text-slate-900"
          : "border-l-transparent text-slate-700 hover:bg-slate-50",
      )}
    >
      <span className="block min-w-0 truncate text-sm">
        {getRecordTitle(record)}
      </span>
      <span className="shrink-0 text-xs text-slate-400">
        {formatListDate(record.updated_at ?? record.created_at)}
      </span>
    </button>
  );
}

function buildKnowledgePreviewUrl(record: UserKnowledgeRecord) {
  const baseUrl = resolveRecordDocumentUrl(record, { preferPreview: !isPdfRecord(record) });
  if (!baseUrl) {
    return null;
  }

  try {
    const url = new URL(baseUrl, window.location.origin);
    const pageNo = getOriginAnchorNumber(record, "page_no");
    const pdfPageNo = getOriginAnchorNumber(record, "pdf_page_no");
    const paragraphNo = getOriginAnchorNumber(record, "paragraph_no");
    const sourceTitle = getRecordTitle(record);

    if (pageNo) {
      url.searchParams.set("page_no", String(pageNo));
    }
    if (pdfPageNo) {
      url.searchParams.set("pdf_page_no", String(pdfPageNo));
    }
    if (paragraphNo) {
      url.searchParams.set("paragraph_no", String(paragraphNo));
    }
    if (sourceTitle) {
      url.searchParams.set("citation_source_title", sourceTitle);
    }
    if (record.source_kind === "import_ref") {
      url.searchParams.set("citation_source_label", "个人知识库收藏");
    } else {
      url.searchParams.set("citation_source_label", "知识库文件");
    }
    if (record.origin_filename && record.origin_filename !== sourceTitle) {
      url.searchParams.set("citation_origin_title", record.origin_filename);
    }

    return `${url.pathname}${url.search}`;
  } catch {
    return baseUrl;
  }
}

export default function KnowledgeLibraryPage() {
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  const { data, isLoading, error } = useUserKnowledgeRecords();
  const deleteMutation = useDeleteUserKnowledgeRecord();
  const uploadMutation = useUploadUserKnowledgeFiles();

  const records = useMemo(
    () => sortRecords((data?.records ?? []).filter(isReferenceRecord)),
    [data?.records],
  );
  const requestedRecordId = searchParams.get("record");

  useEffect(() => {
    document.title = "知识库 - 财政历史大模型";
  }, []);

  useEffect(() => {
    if (records.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && records.some((record) => record.id === current)
        ? current
        : records[0]?.id ?? null,
    );
  }, [records]);

  useEffect(() => {
    if (!requestedRecordId) {
      return;
    }
    const requestedRecord = records.find((record) => record.id === requestedRecordId);
    if (!requestedRecord) {
      return;
    }
    setSelectedRecordId(requestedRecordId);
  }, [records, requestedRecordId]);

  const selectedRecord =
    records.find((record) => record.id === selectedRecordId) ?? records[0] ?? null;
  const selectedPreviewUrl = useMemo(
    () => (selectedRecord ? buildKnowledgePreviewUrl(selectedRecord) : null),
    [selectedRecord],
  );
  const selectedInitialPdfPageNo = useMemo(
    () =>
      selectedRecord
        ? getOriginAnchorNumber(selectedRecord, "pdf_page_no")
          ?? getOriginAnchorNumber(selectedRecord, "page_no")
          ?? 1
        : 1,
    [selectedRecord],
  );

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

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody className="items-center justify-center px-6 py-10">
          <div className="text-sm text-muted-foreground">
            当前为静态模式，知识库功能不可用。
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
      <WorkspaceBody className="min-h-0 overflow-hidden bg-white">
        <div className="flex h-full min-h-0 w-full overflow-hidden bg-white">
          <aside className="flex min-h-0 w-full shrink-0 flex-col border-b border-slate-200 bg-white lg:w-[240px] lg:border-r lg:border-b-0">
            <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
              <div className="text-xs text-slate-500">{records.length} 项</div>
              <div className="flex items-center gap-1">
                {selectedRecord ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 rounded-md px-2 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                    disabled={deleteMutation.isPending}
                    onClick={() => void handleDelete(selectedRecord.id)}
                  >
                    {selectedIsDeleting ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <Trash2Icon className="size-4" />
                    )}
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 rounded-md px-2 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                  onClick={() => setIsUploadDialogOpen(true)}
                >
                  <PlusIcon className="size-4" />
                  上传
                </Button>
              </div>
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
              ) : records.length === 0 ? (
                <div className="p-4 text-sm text-slate-500">
                  暂无资料。
                </div>
              ) : (
                <div>
                  {records.map((record) => (
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
            {!selectedRecord ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    选择左侧资料查看内容
                  </div>
                </div>
              </div>
            ) : !selectedPreviewUrl ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    当前文件暂时没有可展示的预览地址
                  </div>
                  <div className="mt-2 text-xs text-slate-400">
                    来源：{selectedRecord.origin_filename ?? selectedRecord.filename ?? "未知"}
                  </div>
                </div>
              </div>
            ) : (
              <div className="min-h-0 flex-1 p-4 md:p-6">
                <KnowledgeStructuredViewer
                  className="h-full min-h-[640px]"
                  documentUrl={selectedPreviewUrl}
                  initialPdfPageNo={selectedInitialPdfPageNo}
                  excerptable
                  highlightable={false}
                  originFilename={selectedRecord.origin_filename ?? selectedRecord.filename ?? "未知文档"}
                  originTitle={getRecordTitle(selectedRecord)}
                />
              </div>
            )}
          </section>
        </div>

        <Dialog open={isUploadDialogOpen} onOpenChange={setIsUploadDialogOpen}>
          <DialogContent className="sm:max-w-xl border-slate-200 bg-white">
            <DialogHeader>
              <DialogTitle className="text-slate-900">上传资料</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                  setPendingFiles(Array.from(event.target.files ?? []));
                }}
              />
              <Button
                variant="outline"
                className="w-full"
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadIcon className="size-4" />
                选择文件
              </Button>
              <div className="border border-slate-200 p-3 text-xs text-slate-600">
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
                className="bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]"
                onClick={() => void handleUpload()}
                disabled={uploadMutation.isPending || pendingFiles.length === 0}
              >
                {uploadMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : null}
                上传
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
