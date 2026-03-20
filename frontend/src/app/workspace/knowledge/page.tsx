"use client";

import {
  FileIcon,
  Loader2Icon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useDeleteKnowledgeFile, useKnowledgeFiles, useUploadKnowledgeFiles } from "@/core/knowledge/hooks";

type LanguageHint = "unknown" | "zh-Hans" | "zh-Hant" | "en" | "mixed";
type LayoutHint = "unknown" | "horizontal" | "vertical" | "mixed";
type DocumentTypeHint = "unknown" | "book" | "archive" | "periodical" | "ancient_book";
type FileStatusFilter = "all" | "active" | "indexed" | "failed" | "parsed" | "pending_parse" | "uploaded";

const languageOptions: Array<{ value: LanguageHint; label: string }> = [
  { value: "unknown", label: "自动判断" },
  { value: "zh-Hans", label: "简体中文" },
  { value: "zh-Hant", label: "繁体中文" },
  { value: "en", label: "英文" },
  { value: "mixed", label: "混合语言" },
];

const layoutOptions: Array<{ value: LayoutHint; label: string }> = [
  { value: "unknown", label: "自动判断" },
  { value: "horizontal", label: "横排" },
  { value: "vertical", label: "竖排" },
  { value: "mixed", label: "混排" },
];

const documentTypeOptions: Array<{ value: DocumentTypeHint; label: string }> = [
  { value: "unknown", label: "普通文档" },
  { value: "book", label: "书籍" },
  { value: "archive", label: "档案材料" },
  { value: "periodical", label: "期刊报纸" },
  { value: "ancient_book", label: "古籍旧式排印" },
];

const statusFilterOptions: Array<{ value: FileStatusFilter; label: string }> = [
  { value: "all", label: "全部状态" },
  { value: "active", label: "处理中" },
  { value: "indexed", label: "已入库" },
  { value: "failed", label: "失败" },
  { value: "parsed", label: "已解析" },
  { value: "pending_parse", label: "待进一步解析" },
  { value: "uploaded", label: "仅上传" },
];

function statusLabel(status?: string) {
  switch (status) {
    case "queued":
      return "排队中";
    case "parsing":
      return "解析中";
    case "indexing":
      return "入库中";
    case "pending_parse":
      return "待进一步解析";
    case "indexed":
      return "已入库";
    case "parsed":
      return "已解析";
    case "index_failed":
      return "入库失败";
    case "failed":
      return "解析失败";
    case "uploaded":
      return "仅上传";
    default:
      return "未知";
  }
}

function statusVariant(status?: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "indexed":
      return "default";
    case "queued":
    case "parsing":
    case "indexing":
    case "parsed":
      return "secondary";
    case "pending_parse":
      return "outline";
    case "index_failed":
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatCompactTime(value?: number) {
  if (!value) return "未知";
  return new Date(value * 1000).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function languageLabel(value?: string) {
  switch (value) {
    case "zh-Hans":
      return "简体中文";
    case "zh-Hant":
      return "繁体中文";
    case "en":
      return "英文";
    case "mixed":
      return "混合语言";
    default:
      return "自动判断";
  }
}

function layoutLabel(value?: string) {
  switch (value) {
    case "horizontal":
      return "横排";
    case "vertical":
      return "竖排";
    case "mixed":
      return "混排";
    default:
      return "自动判断";
  }
}

function documentTypeLabel(value?: string) {
  switch (value) {
    case "book":
      return "书籍";
    case "archive":
      return "档案材料";
    case "periodical":
      return "期刊报纸";
    case "ancient_book":
      return "古籍旧式排印";
    default:
      return "普通文档";
  }
}

function parseMethodLabel(value?: string) {
  switch (value) {
    case "ocr_pdf_mineru_grpc":
    case "ocr_pdf_local":
    case "paddleocr_pdf":
      return "OCR 解析";
    case "static":
      return "直接导入";
    default:
      return "自动解析";
  }
}

function fileStatusHint(file: {
  parse_status?: string;
  parse_method?: string;
  indexable?: boolean;
}) {
  switch (file.parse_status) {
    case "queued":
      return "等待开始处理";
    case "parsing":
      return "正在提取文本";
    case "indexing":
      return "正在写入知识库";
    case "pending_parse":
      return "当前文件需要进一步处理后才能入库";
    case "index_failed":
      return "入库失败，请稍后重试";
    case "failed":
      return file.parse_method?.includes("ocr")
        ? "解析失败，请检查解析服务后重试"
        : "处理失败，请稍后重试";
    case "uploaded":
      return file.indexable === false ? "已上传，暂不支持自动入库" : "已上传";
    default:
      return null;
  }
}

export default function KnowledgeManagementPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadLanguageHint, setUploadLanguageHint] = useState<LanguageHint>("unknown");
  const [uploadLayoutHint, setUploadLayoutHint] = useState<LayoutHint>("unknown");
  const [uploadDocumentTypeHint, setUploadDocumentTypeHint] =
    useState<DocumentTypeHint>("unknown");
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);

  const { data, isLoading, error, refetch, isFetching } = useKnowledgeFiles();
  const uploadMutation = useUploadKnowledgeFiles();
  const deleteMutation = useDeleteKnowledgeFile();

  useEffect(() => {
    document.title = "知识库管理 - 财政历史大模型";
  }, []);

  const summary = useMemo(() => {
    const files = data?.files ?? [];
    const activeStatuses = new Set(["queued", "parsing", "indexing"]);
    const activeFiles = files.filter((file) =>
      activeStatuses.has(file.parse_status ?? ""),
    );
    const indexed = files.filter((file) => file.parse_status === "indexed").length;
    const failed = files.filter((file) =>
      ["failed", "index_failed"].includes(file.parse_status ?? ""),
    ).length;
    return {
      total: files.length,
      indexed,
      failed,
      active: activeFiles.length,
      progress: files.length > 0 ? Math.round((indexed / files.length) * 100) : 0,
    };
  }, [data?.files]);

  const sortedFiles = useMemo(() => {
    const files = [...(data?.files ?? [])];
    files.sort((a, b) => {
      const timeDelta = (b.modified ?? 0) - (a.modified ?? 0);
      if (timeDelta !== 0) {
        return timeDelta;
      }
      return a.filename.localeCompare(b.filename, "zh-CN");
    });
    return files;
  }, [data?.files]);

  const filteredFiles = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();

    return sortedFiles.filter((file) => {
      const matchesStatus =
        statusFilter === "all"
          ? true
          : statusFilter === "active"
            ? ["queued", "parsing", "indexing"].includes(file.parse_status ?? "")
            : statusFilter === "failed"
              ? ["failed", "index_failed"].includes(file.parse_status ?? "")
              : file.parse_status === statusFilter;

      if (!matchesStatus) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      const haystack = [
        file.filename,
        file.parse_method,
        file.extension,
        file.parse_status,
        file.hints?.document_type_hint,
        file.hints?.language_hint,
        file.hints?.layout_hint,
        file.preview_filename,
        file.structured_filename,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(keyword);
    });
  }, [searchQuery, sortedFiles, statusFilter]);

  const resetUploadDialog = () => {
    setPendingFiles([]);
    setIsUploadDialogOpen(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleOpenUploadDialog = () => {
    setIsUploadDialogOpen(true);
  };

  const handlePickFiles = () => {
    fileInputRef.current?.click();
  };

  const handleFilesSelected = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setPendingFiles(files);
    event.target.value = "";
  };

  const handleUploadSubmit = async () => {
    if (pendingFiles.length === 0) {
      toast.error("请先选择要上传的文件");
      return;
    }

    try {
      const result = await uploadMutation.mutateAsync({
        files: pendingFiles,
        options: {
          languageHint: uploadLanguageHint === "unknown" ? undefined : uploadLanguageHint,
          layoutHint: uploadLayoutHint === "unknown" ? undefined : uploadLayoutHint,
          documentTypeHint:
            uploadDocumentTypeHint === "unknown" ? undefined : uploadDocumentTypeHint,
        },
      });
      toast.success(result.message);
      resetUploadDialog();
      void refetch();
    } catch (uploadError) {
      const message =
        uploadError instanceof Error ? uploadError.message : "上传失败";
      toast.error(message);
    }
  };

  const handleDelete = async (filename: string) => {
    setDeletingFilename(filename);
    try {
      const result = await deleteMutation.mutateAsync(filename);
      toast.success(result.message);
    } catch (deleteError) {
      const message =
        deleteError instanceof Error ? deleteError.message : "删除失败";
      toast.error(message);
    } finally {
      setDeletingFilename(null);
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="bg-[linear-gradient(180deg,_rgba(250,247,242,1),_rgba(245,241,236,1))]">
        <div className="flex h-full w-full min-w-0 flex-1 flex-col px-3 py-3 lg:px-4">
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-stone-200/90 bg-white/95 shadow-sm">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFilesSelected}
            />
            <Dialog
              open={isUploadDialogOpen}
              onOpenChange={(open) => {
                if (!open && !uploadMutation.isPending) {
                  resetUploadDialog();
                  return;
                }
                setIsUploadDialogOpen(open);
              }}
            >
              <DialogContent className="max-w-2xl border-stone-200 bg-stone-50/95">
                <DialogHeader>
                  <DialogTitle className="text-stone-950">上传知识库文件</DialogTitle>
                  <DialogDescription>
                    上传前补充 OCR 线索，系统会默认从 PDF 第 1 页开始编号。
                  </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4">
                  <div className="rounded-xl border border-stone-200 bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-stone-950">
                          选择文件
                        </div>
                        <div className="text-xs text-stone-500">
                          PDF、Markdown、Office 文档都可以批量上传。
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="border-stone-300 bg-white text-stone-700"
                        onClick={handlePickFiles}
                        disabled={uploadMutation.isPending}
                      >
                        选择文件
                      </Button>
                    </div>

                    <div className="mt-3 rounded-lg border border-dashed border-stone-200 bg-stone-50 p-3">
                      {pendingFiles.length === 0 ? (
                        <div className="text-sm text-stone-500">
                          还没有选择文件。
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <div className="text-sm font-medium text-stone-900">
                            已选择 {pendingFiles.length} 个文件
                          </div>
                          <div className="max-h-28 space-y-1 overflow-auto text-xs text-stone-600">
                            {pendingFiles.map((file) => (
                              <div key={`${file.name}-${file.size}`}>{file.name}</div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="grid gap-3 rounded-xl border border-stone-200 bg-white p-4 md:grid-cols-3">
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-stone-700">文档类型</div>
                      <Select
                        value={uploadDocumentTypeHint}
                        onValueChange={(value) =>
                          setUploadDocumentTypeHint(value as DocumentTypeHint)
                        }
                      >
                        <SelectTrigger className="bg-white text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {documentTypeOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-stone-700">语言线索</div>
                      <Select
                        value={uploadLanguageHint}
                        onValueChange={(value) => setUploadLanguageHint(value as LanguageHint)}
                      >
                        <SelectTrigger className="bg-white text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {languageOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-stone-700">版式线索</div>
                      <Select
                        value={uploadLayoutHint}
                        onValueChange={(value) => setUploadLayoutHint(value as LayoutHint)}
                      >
                        <SelectTrigger className="bg-white text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {layoutOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                </div>

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    className="border-stone-300 bg-white text-stone-700"
                    onClick={resetUploadDialog}
                    disabled={uploadMutation.isPending}
                  >
                    取消
                  </Button>
                  <Button
                    type="button"
                    className="bg-stone-900 text-white hover:bg-stone-800"
                    onClick={() => void handleUploadSubmit()}
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

            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-700">
                  文档 <span className="ml-1 font-semibold text-stone-950">{summary.total}</span>
                </div>
                <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-700">
                  已入库 <span className="ml-1 font-semibold text-stone-950">{summary.indexed}</span>
                </div>
                <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-700">
                  处理中 <span className="ml-1 font-semibold text-stone-950">{summary.active}</span>
                </div>
                <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-700">
                  失败 <span className="ml-1 font-semibold text-stone-950">{summary.failed}</span>
                </div>
                {summary.active > 0 && (
                  <div className="text-muted-foreground text-xs">
                    正在自动刷新队列状态
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 border-stone-300 bg-white px-2.5 text-stone-700"
                  onClick={() => void refetch()}
                  disabled={isFetching}
                >
                  <RefreshCwIcon
                    className={isFetching ? "size-4 animate-spin" : "size-4"}
                  />
                </Button>
                <Button
                  size="sm"
                  className="h-8 rounded-md bg-stone-900 px-3 text-white hover:bg-stone-800"
                  onClick={handleOpenUploadDialog}
                  disabled={uploadMutation.isPending}
                >
                  {uploadMutation.isPending ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <UploadIcon className="size-4" />
                  )}
                  上传文件
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-2 border-b border-stone-200 px-4 py-3">
              <div className="w-[140px]">
                <Select
                  value={statusFilter}
                  onValueChange={(value) => setStatusFilter(value as FileStatusFilter)}
                >
                  <SelectTrigger className="h-8 bg-white text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {statusFilterOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="relative min-w-[240px] flex-1">
                <SearchIcon className="text-muted-foreground absolute left-3 top-1/2 size-3.5 -translate-y-1/2" />
                <Input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索书名、文件名、解析方式"
                  className="h-8 bg-white pl-8 text-xs"
                />
              </div>

            </div>

            {isLoading ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center gap-2 text-sm">
                <Loader2Icon className="size-4 animate-spin" />
                正在加载知识库文件列表
              </div>
            ) : error ? (
              <div className="m-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {error.message}
              </div>
            ) : filteredFiles.length === 0 ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center px-6 text-sm">
                {sortedFiles.length === 0
                  ? "还没有全局知识库文档。"
                  : "没有符合当前筛选条件的文件。"}
              </div>
            ) : (
              <ScrollArea className="min-h-0 flex-1">
                <Table className="min-w-[1120px] text-xs">
                  <TableHeader className="sticky top-0 z-10 bg-stone-50/95 backdrop-blur">
                    <TableRow className="hover:bg-stone-50/95">
                      <TableHead className="w-[30%]">文件</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>线索</TableHead>
                      <TableHead>大小</TableHead>
                      <TableHead>时间</TableHead>
                      <TableHead>产物</TableHead>
                      <TableHead className="w-[52px] text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredFiles.map((file) => {
                      const isDeleting =
                        deleteMutation.isPending &&
                        deletingFilename === file.filename;
                      const methodLabel = parseMethodLabel(file.parse_method);
                      const statusHint = fileStatusHint(file);

                      return (
                        <TableRow key={file.filename} className="h-14">
                          <TableCell className="py-2.5">
                            <div className="flex items-center gap-2">
                              <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-stone-100 text-stone-500">
                                <FileIcon className="size-3.5" />
                              </div>
                              <div className="min-w-0">
                                <div className="truncate font-medium text-[13px] text-stone-950">
                                  {file.filename}
                                </div>
                                <div className="truncate text-[11px] text-stone-500">
                                  {`解析：${methodLabel}`}
                                  {statusHint ? ` · ${statusHint}` : ""}
                                </div>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="py-2.5 text-[12px] text-stone-700">
                            <div>{documentTypeLabel(file.hints?.document_type_hint)}</div>
                            {file.extension && (
                              <div className="text-[11px] text-stone-500">
                                {file.extension.replace(/^\./, "").toUpperCase()}
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="py-2.5">
                            <Badge
                              variant={statusVariant(file.parse_status)}
                              className="h-5 rounded-md px-2 text-[11px]"
                            >
                              {statusLabel(file.parse_status)}
                            </Badge>
                          </TableCell>
                          <TableCell className="py-2.5 text-[12px] text-stone-600">
                            <div>
                              {languageLabel(file.hints?.language_hint)}
                              <span className="mx-1 text-stone-300">/</span>
                              {layoutLabel(file.hints?.layout_hint)}
                            </div>
                          </TableCell>
                          <TableCell className="py-2.5 text-[12px] text-stone-700">
                            {formatBytes(file.size)}
                          </TableCell>
                          <TableCell className="py-2.5 text-[12px] text-stone-700">
                            {formatCompactTime(file.modified)}
                          </TableCell>
                          <TableCell className="py-2.5 text-[12px]">
                            <div className="flex flex-wrap gap-x-3 gap-y-1">
                              <a
                                className="text-stone-700 underline underline-offset-4 hover:text-stone-950"
                                href={file.artifact_url}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                原文
                              </a>
                              {file.preview_filename &&
                                file.preview_filename !== file.filename &&
                                file.preview_artifact_url && (
                                  <a
                                    className="text-stone-700 underline underline-offset-4 hover:text-stone-950"
                                    href={file.preview_artifact_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    解析
                                  </a>
                                )}
                              {file.structured_filename && (
                                <span
                                  className="truncate text-stone-600"
                                  title={file.structured_filename}
                                >
                                  结构化
                                </span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="py-1.5 text-right">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              disabled={deleteMutation.isPending}
                              onClick={() => void handleDelete(file.filename)}
                            >
                              {isDeleting ? (
                                <Loader2Icon className="size-3.5 animate-spin" />
                              ) : (
                                <Trash2Icon className="size-3.5" />
                              )}
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </ScrollArea>
            )}
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
