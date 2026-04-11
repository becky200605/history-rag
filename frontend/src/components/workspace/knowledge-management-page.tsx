"use client";

import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowUpIcon,
  BookmarkPlusIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CheckSquareIcon,
  FileIcon,
  FolderIcon,
  Loader2Icon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SquareIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
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
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  buildKnowledgeDocumentUrl,
  type KnowledgeFileInfo,
} from "@/core/knowledge/api";
import {
  useDeleteKnowledgeFile,
  useKnowledgeFiles,
  useRegenerateKnowledgeFileMetadata,
  useRetryKnowledgeFileIndexing,
  useUploadKnowledgeFiles,
  useUpdateKnowledgeFileMetadata,
} from "@/core/knowledge/hooks";
import type { UserKnowledgeSpace } from "@/core/knowledge/user-api";
import {
  useCreateUserKnowledgeSpace,
  useDeleteUserKnowledgeRecord,
  useDeleteUserKnowledgeSpace,
  useMoveUserKnowledgeRecord,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecords,
  useUserKnowledgeSpaces,
} from "@/core/knowledge/user-hooks";
import { cn } from "@/lib/utils";

type LanguageHint = "unknown" | "zh-Hans" | "zh-Hant" | "en" | "mixed";
type LayoutHint = "unknown" | "horizontal" | "vertical" | "mixed";
type DocumentTypeHint = "unknown" | "book" | "archive" | "periodical" | "ancient_book";
type FileStatusFilter = "all" | "active" | "indexed" | "failed" | "parsed" | "pending_parse" | "uploaded";
type KnowledgeType = "core" | "specialized" | "reference" | "unknown";
const KNOWLEDGE_TYPES = new Set(["core", "specialized", "reference", "unknown"]);

type FolderTreeNode = {
  name: string;
  path: string;
  fileCount: number;
  children: FolderTreeNode[];
  source: "global" | "personal" | "mixed";
  spaceId?: string;
  deletable?: boolean;
};

type ManagedKnowledgeFile = {
  rowId: string;
  source: "global" | "personal";
  scope: "global" | "user";
  docId?: string | null;
  filename: string;
  title: string;
  folderPath: string;
  folderDisplay: string;
  size: number;
  modified?: number;
  parseMethod?: string;
  parseStatus?: string;
  indexable?: boolean;
  documentUrl?: string | null;
  artifactUrl?: string | null;
  extension?: string | null;
  previewFilename?: string | null;
  previewArtifactUrl?: string | null;
  structuredFilename?: string | null;
  type?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  tags?: string[];
  hints?: Record<string, string>;
  knowledgeSpaceId?: string | null;
  knowledgeSpaceName?: string | null;
  userRecordId?: string | null;
};

function buildFileTags(file: {
  tags?: string[];
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
}) {
  const tags = file.tags?.length
    ? file.tags
    : [
        ...(file.categories ?? []),
        ...(file.eras ?? []),
        ...(file.regions ?? []),
        ...(file.keywords ?? []),
      ];

  return Array.from(
    new Set(
      tags.filter(
        (tag) => tag && !KNOWLEDGE_TYPES.has(String(tag).trim().toLowerCase()),
      ),
    ),
  );
}

function normalizeFolderPath(value?: string | null) {
  const normalized = (value ?? "")
    .replace(/\\/g, "/")
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .join("/");
  return normalized || "未分类";
}

function getFileFolderPath(file: { folder?: string | null; tags?: string[] }) {
  const explicit = normalizeFolderPath(file.folder);
  if (explicit !== "未分类") {
    return explicit;
  }
  const firstTag = file.tags?.find((tag) => tag?.trim());
  return normalizeFolderPath(firstTag ?? null);
}

function buildFolderTree(files: Array<{ folder?: string | null; tags?: string[] }>): FolderTreeNode[] {
  type MutableNode = { children: Map<string, MutableNode>; fileCount: number };

  const ensureNode = (map: Map<string, MutableNode>, key: string): MutableNode => {
    const existing = map.get(key);
    if (existing) {
      return existing;
    }
    const next: MutableNode = { children: new Map(), fileCount: 0 };
    map.set(key, next);
    return next;
  };

  const mutableRoot = new Map<string, MutableNode>();
  for (const file of files) {
    const segments = getFileFolderPath(file).split("/");
    let current = mutableRoot;
    for (const segment of segments) {
      const node = ensureNode(current, segment);
      node.fileCount += 1;
      current = node.children;
    }
  }

  const toTree = (map: Map<string, MutableNode>, parentPath = ""): FolderTreeNode[] =>
    Array.from(map.entries())
      .sort(([left], [right]) => left.localeCompare(right, "zh-CN"))
      .map(([name, node]) => {
        const path = parentPath ? `${parentPath}/${name}` : name;
        return {
          name,
          path,
          fileCount: node.fileCount,
          children: toTree(node.children, path),
          source: "global",
        };
      });

  return toTree(mutableRoot);
}

function buildPersonalFolderTree(
  spaces: UserKnowledgeSpace[],
  files: ManagedKnowledgeFile[],
): FolderTreeNode[] {
  return [...spaces]
    .filter((space) => space.type === "personal")
    .sort((left, right) => {
      if (left.is_default && !right.is_default) {
        return -1;
      }
      if (!left.is_default && right.is_default) {
        return 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    })
    .map((space) => ({
      name: space.name,
      path: `personal:${space.id}`,
      fileCount: files.filter((file) => file.source === "personal" && file.knowledgeSpaceId === space.id).length,
      children: [],
      source: "personal",
      spaceId: space.id,
      deletable: !space.is_default && !space.readonly,
    }));
}

function knowledgeTypeLabel(value?: string | null) {
  switch ((value ?? "").toLowerCase()) {
    case "core":
      return "核心通用";
    case "specialized":
      return "专题支撑";
    case "reference":
      return "参考工具";
    default:
      return "未分类";
  }
}

const knowledgeTypeOptions: Array<{ value: KnowledgeType; label: string }> = [
  { value: "unknown", label: "未分类" },
  { value: "core", label: "核心通用" },
  { value: "specialized", label: "专题支撑" },
  { value: "reference", label: "参考工具" },
];

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

function splitTagInput(value: string) {
  return value
    .split(/[,\n，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinTagInput(values?: string[]) {
  return (values ?? []).join(", ");
}

function formatCompactTime(value?: number) {
  if (!value) return "未知";
  const normalized = value < 1_000_000_000_000 ? value * 1000 : value;
  return new Date(normalized).toLocaleString("zh-CN", {
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
  parseStatus?: string;
  parse_method?: string;
  parseMethod?: string;
  indexable?: boolean;
}) {
  const status = file.parseStatus ?? file.parse_status;
  const method = file.parseMethod ?? file.parse_method;
  switch (status) {
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
      return method?.includes("ocr")
        ? "解析失败，请检查解析服务后重试"
        : "处理失败，请稍后重试";
    case "uploaded":
      return file.indexable === false ? "已上传，暂不支持自动入库" : "已上传";
    default:
      return null;
  }
}

function retryActionLabel(status?: string) {
  switch (status) {
    case "failed":
      return "重新解析";
    case "index_failed":
      return "重新入库";
    case "indexed":
      return "重新入库";
    default:
      return "重试";
  }
}

function buildManagedFileReaderHref(file: ManagedKnowledgeFile) {
  const documentUrl =
    file.documentUrl
    ?? file.artifactUrl
    ?? (file.scope === "user"
      ? buildKnowledgeDocumentUrl("user", file.filename)
      : buildKnowledgeDocumentUrl("global", file.filename));

  if (!documentUrl) {
    return null;
  }

  const params = new URLSearchParams({
    mode: "reader",
    filename: file.filename,
    scope: file.scope,
    document_url: documentUrl,
    origin_title: file.title,
    origin_filename: file.filename,
    back_href: "/workspace/knowledge-manage",
    back_label: "知识库管理",
  });

  if (file.knowledgeSpaceId) {
    params.set("knowledge_space_id", file.knowledgeSpaceId);
  }

  return `/workspace/knowledge/view?${params.toString()}`;
}

function FolderTreeBranch({
  node,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
  depth = 0,
}: {
  node: FolderTreeNode;
  selectedPath: string;
  expandedPaths: string[];
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  depth?: number;
}) {
  const isExpanded = expandedPaths.includes(node.path);
  const isSelected = selectedPath === node.path;
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <button
        type="button"
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition",
          isSelected
            ? "bg-[rgb(241,248,249)] text-[rgb(23,89,108)]"
            : "text-slate-700 hover:bg-slate-50",
        )}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => onSelect(node.path)}
      >
        <span
          className="inline-flex size-4 shrink-0 items-center justify-center text-slate-400"
          onClick={(event) => {
            event.stopPropagation();
            if (hasChildren) {
              onToggle(node.path);
            }
          }}
        >
          {hasChildren ? (
            isExpanded ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />
          ) : (
            <span className="size-3.5" />
          )}
        </span>
        <FolderIcon className="size-4 shrink-0 text-[rgb(57,130,152)]" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-xs text-slate-400">{node.fileCount}</span>
      </button>

      {hasChildren && isExpanded ? (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <FolderTreeBranch
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={onSelect}
              onToggle={onToggle}
              depth={depth + 1}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function KnowledgeManagementPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isCreateFolderDialogOpen, setIsCreateFolderDialogOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadLanguageHint, setUploadLanguageHint] = useState<LanguageHint>("unknown");
  const [uploadLayoutHint, setUploadLayoutHint] = useState<LayoutHint>("unknown");
  const [uploadDocumentTypeHint, setUploadDocumentTypeHint] =
    useState<DocumentTypeHint>("unknown");
  const [statusFilter, setStatusFilter] = useState<FileStatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [retryingFilename, setRetryingFilename] = useState<string | null>(null);
  const [movingRecord, setMovingRecord] = useState<ManagedKnowledgeFile | null>(null);
  const [moveTargetSpaceId, setMoveTargetSpaceId] = useState<string>("");
  const [newFolderName, setNewFolderName] = useState("");
  const [editingFile, setEditingFile] = useState<KnowledgeFileInfo | null>(null);
  const [typeInput, setTypeInput] = useState<KnowledgeType>("unknown");
  const [folderInput, setFolderInput] = useState("");
  const [categoriesInput, setCategoriesInput] = useState("");
  const [erasInput, setErasInput] = useState("");
  const [regionsInput, setRegionsInput] = useState("");
  const [keywordsInput, setKeywordsInput] = useState("");
  const [summaryInput, setSummaryInput] = useState("");
  const [languageHintInput, setLanguageHintInput] = useState<LanguageHint>("unknown");
  const [layoutHintInput, setLayoutHintInput] = useState<LayoutHint>("unknown");
  const [documentTypeHintInput, setDocumentTypeHintInput] =
    useState<DocumentTypeHint>("unknown");
  const [selectedFolderPath, setSelectedFolderPath] = useState<string>("all");
  const [expandedFolderPaths, setExpandedFolderPaths] = useState<string[]>([]);


  const { data, isLoading, error, refetch, isFetching } = useKnowledgeFiles();
  const personalSpacesQuery = useUserKnowledgeSpaces();
  const personalRecordsQuery = useUserKnowledgeRecords();
  const uploadMutation = useUploadKnowledgeFiles();
  const uploadUserMutation = useUploadUserKnowledgeFiles();
  const deleteMutation = useDeleteKnowledgeFile();
  const deleteUserRecordMutation = useDeleteUserKnowledgeRecord();
  const retryMutation = useRetryKnowledgeFileIndexing();
  const createSpaceMutation = useCreateUserKnowledgeSpace();
  const deleteSpaceMutation = useDeleteUserKnowledgeSpace();
  const moveUserRecordMutation = useMoveUserKnowledgeRecord();
  const updateMetadataMutation = useUpdateKnowledgeFileMetadata();
  const regenerateMetadataMutation = useRegenerateKnowledgeFileMetadata();
  const metadataDialogError =
    updateMetadataMutation.error ?? regenerateMetadataMutation.error;

  useEffect(() => {
    document.title = "知识库管理 - 财政历史智能知识库";
  }, []);

  const summary = useMemo(() => {
    const globalFiles = data?.files ?? [];
    const personalRecords = (personalRecordsQuery.data?.records ?? []).filter(
      (record) => ["upload", "import_ref"].includes(record.source_kind),
    );
    const activeStatuses = new Set(["queued", "parsing", "indexing"]);
    const activeFiles = [
      ...globalFiles,
      ...personalRecords.map((record) => ({
        parse_status: record.parse_status,
      })),
    ].filter((file) =>
      activeStatuses.has(file.parse_status ?? ""),
    );
    const indexed =
      globalFiles.filter((file) => file.parse_status === "indexed").length +
      personalRecords.filter((record) => record.parse_status === "indexed").length;
    const failed =
      globalFiles.filter((file) => ["failed", "index_failed"].includes(file.parse_status ?? "")).length +
      personalRecords.filter((record) => ["failed", "index_failed"].includes(record.parse_status ?? "")).length;
    const total = globalFiles.length + personalRecords.length;
    return {
      total,
      indexed,
      failed,
      active: activeFiles.length,
      progress: total > 0 ? Math.round((indexed / total) * 100) : 0,
    };
  }, [data?.files, personalRecordsQuery.data?.records]);

  const sortedGlobalFiles = useMemo(() => {
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

  const personalSpaces = useMemo(
    () => (personalSpacesQuery.data?.spaces ?? []).filter((space) => space.type === "personal"),
    [personalSpacesQuery.data?.spaces],
  );
  const defaultPersonalSpace = useMemo(
    () => personalSpaces.find((space) => space.is_default) ?? personalSpaces[0] ?? null,
    [personalSpaces],
  );

  const managedFiles = useMemo<ManagedKnowledgeFile[]>(() => {
    const globalRows = sortedGlobalFiles.map<ManagedKnowledgeFile>((file) => ({
      rowId: `global:${file.filename}`,
      source: "global",
      scope: "global",
      docId: file.doc_id ?? null,
      filename: file.filename,
      title: file.filename.replace(/\.[^.]+$/, ""),
      folderPath: `system:${getFileFolderPath(file)}`,
      folderDisplay: getFileFolderPath(file),
      size: file.size,
      modified: file.modified,
      parseMethod: file.parse_method,
      parseStatus: file.parse_status,
      indexable: file.indexable,
      documentUrl: buildKnowledgeDocumentUrl("global", file.filename),
      artifactUrl: file.artifact_url,
      extension: file.extension,
      previewFilename: file.preview_filename,
      previewArtifactUrl: file.preview_artifact_url,
      structuredFilename: file.structured_filename,
      type: file.type,
      categories: file.categories,
      eras: file.eras,
      regions: file.regions,
      keywords: file.keywords,
      summary: file.summary,
      tags: file.tags,
      hints: file.hints,
    }));

    const personalRows = (personalRecordsQuery.data?.records ?? [])
      .filter((record) => ["upload", "import_ref"].includes(record.source_kind))
      .map<ManagedKnowledgeFile>((record) => {
        const sourceFilename = record.filename ?? record.origin_filename ?? `${record.id}.md`;
        const documentUrl =
          record.artifact_url
          ?? (record.origin_scope === "global" && record.origin_filename
            ? buildKnowledgeDocumentUrl("global", record.origin_filename)
            : buildKnowledgeDocumentUrl("user", sourceFilename));
        const artifactUrl =
          documentUrl;
        const previewArtifactUrl =
          record.preview_artifact_url
          ?? artifactUrl;
        return {
          rowId: `personal:${record.id}`,
          source: "personal",
          scope: "user",
          docId: record.id,
          filename: sourceFilename,
          title: record.display_title ?? record.title ?? sourceFilename.replace(/\.[^.]+$/, ""),
          folderPath: `personal:${record.knowledge_space_id ?? defaultPersonalSpace?.id ?? ""}`,
          folderDisplay: record.knowledge_space_name ?? "默认个人知识库",
          size: record.size,
          modified: record.updated_at ? new Date(record.updated_at).getTime() : undefined,
          parseMethod: record.parse_method ?? undefined,
          parseStatus: record.parse_status ?? undefined,
          indexable: record.indexable,
          documentUrl,
          artifactUrl,
          extension: record.extension ?? undefined,
          previewFilename: record.preview_filename ?? undefined,
          previewArtifactUrl,
          structuredFilename: record.structured_filename ?? undefined,
          hints: record.hints ?? undefined,
          knowledgeSpaceId: record.knowledge_space_id ?? undefined,
          knowledgeSpaceName: record.knowledge_space_name ?? undefined,
          userRecordId: record.id,
        };
      });
    return [...personalRows, ...globalRows];
  }, [defaultPersonalSpace?.id, personalRecordsQuery.data?.records, sortedGlobalFiles]);

  const filteredFiles = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();

    return managedFiles.filter((file) => {
      const matchesStatus =
        statusFilter === "all"
          ? true
          : statusFilter === "active"
            ? ["queued", "parsing", "indexing"].includes(file.parseStatus ?? "")
            : statusFilter === "failed"
              ? ["failed", "index_failed"].includes(file.parseStatus ?? "")
              : file.parseStatus === statusFilter;

      if (!matchesStatus) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      const haystack = [
        file.title,
        file.filename,
        file.folderDisplay,
        file.type,
        ...(file.tags ?? []),
        ...(file.categories ?? []),
        ...(file.eras ?? []),
        ...(file.regions ?? []),
        ...(file.keywords ?? []),
        file.summary,
        file.parseMethod,
        file.extension,
        file.parseStatus,
        file.hints?.document_type_hint,
        file.hints?.language_hint,
        file.hints?.layout_hint,
        file.previewFilename,
        file.structuredFilename,
        file.knowledgeSpaceName,
        file.source === "global" ? "系统" : "个人",
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(keyword);
    });
  }, [managedFiles, searchQuery, statusFilter]);

  const systemFolderTree = useMemo(() => {
    const tree = buildFolderTree(sortedGlobalFiles).map((node) => ({
      ...node,
      path: `system:${node.path}`,
      source: "global" as const,
      children: node.children.map(function relabel(child): FolderTreeNode {
        return {
          ...child,
          path: `system:${child.path}`,
          source: "global",
          children: child.children.map(relabel),
        };
      }),
    }));
    return tree;
  }, [sortedGlobalFiles]);
  const personalFolderTree = useMemo(
    () => buildPersonalFolderTree(personalSpaces, managedFiles),
    [managedFiles, personalSpaces],
  );
  const folderTree = useMemo<FolderTreeNode[]>(
    () => [
      {
        name: "个人",
        path: "personal-root",
        fileCount: managedFiles.filter((file) => file.source === "personal").length,
        children: personalFolderTree,
        source: "personal",
      },
      {
        name: "系统",
        path: "system-root",
        fileCount: managedFiles.filter((file) => file.source === "global").length,
        children: systemFolderTree,
        source: "global",
      },
    ],
    [managedFiles, personalFolderTree, systemFolderTree],
  );

  useEffect(() => {
    setExpandedFolderPaths((current) => {
      if (current.length > 0) {
        return current;
      }
      const paths: string[] = [];
      const visit = (nodes: FolderTreeNode[]) => {
        for (const node of nodes) {
          paths.push(node.path);
          visit(node.children);
        }
      };
      visit(folderTree);
      return paths;
    });
  }, [folderTree]);

  useEffect(() => {
    if (selectedFolderPath === "all") {
      return;
    }
    const availablePaths = new Set<string>();
    const visit = (nodes: FolderTreeNode[]) => {
      for (const node of nodes) {
        availablePaths.add(node.path);
        visit(node.children);
      }
    };
    visit(folderTree);
    if (!availablePaths.has(selectedFolderPath)) {
      setSelectedFolderPath("all");
    }
  }, [folderTree, selectedFolderPath]);

  const folderFilteredFiles = useMemo(() => {
    if (selectedFolderPath === "all") {
      return filteredFiles;
    }
    if (selectedFolderPath === "personal-root") {
      return filteredFiles.filter((file) => file.source === "personal");
    }
    if (selectedFolderPath === "system-root") {
      return filteredFiles.filter((file) => file.source === "global");
    }
    if (selectedFolderPath.startsWith("personal:")) {
      return filteredFiles.filter((file) => file.folderPath === selectedFolderPath);
    }
    return filteredFiles.filter((file) => {
      return file.folderPath === selectedFolderPath || file.folderPath.startsWith(`${selectedFolderPath}/`);
    });
  }, [filteredFiles, selectedFolderPath]);

  useEffect(() => {
    const visibleRowIds = new Set(folderFilteredFiles.map((file) => file.rowId));
    setSelectedRowIds((current) =>
      current.filter((rowId) => visibleRowIds.has(rowId)),
    );
  }, [folderFilteredFiles]);

  const selectedFiles = useMemo(
    () => folderFilteredFiles.filter((file) => selectedRowIds.includes(file.rowId)),
    [folderFilteredFiles, selectedRowIds],
  );
  const selectableVisibleFiles = useMemo(
    () =>
      folderFilteredFiles.filter(
        (file) => Boolean(file.docId) && file.parseStatus === "indexed",
      ),
    [folderFilteredFiles],
  );

  const allVisibleSelected =
    selectableVisibleFiles.length > 0 &&
    selectedFiles.length === selectableVisibleFiles.length;

  const selectedMaterialsPayload = useMemo(
    () =>
      selectedFiles
        .filter((file) => Boolean(file.docId) && file.parseStatus === "indexed")
        .map((file) => ({
          doc_id: String(file.docId),
          title: file.title,
          filename: file.filename,
          scope: file.scope,
        })),
    [selectedFiles],
  );

  const selectedPersonalSpace = useMemo(
    () =>
      selectedFolderPath.startsWith("personal:")
        ? personalSpaces.find((space) => `personal:${space.id}` === selectedFolderPath) ?? null
        : null,
    [personalSpaces, selectedFolderPath],
  );
  const uploadTargetMode =
    selectedFolderPath === "system-root" || selectedFolderPath.startsWith("system:")
      ? "global"
      : "personal";
  const uploadTargetPersonalSpace = selectedPersonalSpace ?? defaultPersonalSpace;
  const selectedFolderNode = useMemo(() => {
    const visit = (nodes: FolderTreeNode[]): FolderTreeNode | null => {
      for (const node of nodes) {
        if (node.path === selectedFolderPath) {
          return node;
        }
        const nested = visit(node.children);
        if (nested) {
          return nested;
        }
      }
      return null;
    };
    return visit(folderTree);
  }, [folderTree, selectedFolderPath]);

  const breadcrumbs = useMemo(() => {
    if (selectedFolderPath === "all") return [];
    const path: { name: string; path: string }[] = [];
    const findPath = (nodes: FolderTreeNode[], target: string): boolean => {
      for (const node of nodes) {
        path.push({ name: node.name, path: node.path });
        if (node.path === target) return true;
        if (findPath(node.children, target)) return true;
        path.pop();
      }
      return false;
    };
    findPath(folderTree, selectedFolderPath);
    return path;
  }, [folderTree, selectedFolderPath]);

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
      const uploadOptions = {
        languageHint: uploadLanguageHint === "unknown" ? undefined : uploadLanguageHint,
        layoutHint: uploadLayoutHint === "unknown" ? undefined : uploadLayoutHint,
        documentTypeHint:
          uploadDocumentTypeHint === "unknown" ? undefined : uploadDocumentTypeHint,
      };
      const result =
        uploadTargetMode === "global"
          ? await uploadMutation.mutateAsync({
              files: pendingFiles,
              options: uploadOptions,
            })
          : await uploadUserMutation.mutateAsync({
              files: pendingFiles,
              options: {
                ...uploadOptions,
                knowledgeSpaceId: uploadTargetPersonalSpace?.id,
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

  const handleDeletePersonalRecord = async (recordId: string) => {
    setDeletingRecordId(recordId);
    try {
      const result = await deleteUserRecordMutation.mutateAsync(recordId);
      toast.success(result.message);
    } catch (deleteError) {
      const message =
        deleteError instanceof Error ? deleteError.message : "删除失败";
      toast.error(message);
    } finally {
      setDeletingRecordId(null);
    }
  };

  const handleRetryIndexing = async (filename: string) => {
    setRetryingFilename(filename);
    try {
      const result = await retryMutation.mutateAsync(filename);
      toast.success(result.message);
    } catch (retryError) {
      const message =
        retryError instanceof Error ? retryError.message : "重新入库失败";
      toast.error(message);
    } finally {
      setRetryingFilename(null);
    }
  };

  const handleCreateFolder = async () => {
    const trimmedName = newFolderName.trim();
    if (!trimmedName) {
      toast.error("请输入文件夹名称");
      return;
    }
    try {
      const result = await createSpaceMutation.mutateAsync({ name: trimmedName });
      toast.success(result.message);
      setNewFolderName("");
      setIsCreateFolderDialogOpen(false);
      setSelectedFolderPath(`personal:${result.space.id}`);
    } catch (createError) {
      const message =
        createError instanceof Error ? createError.message : "创建文件夹失败";
      toast.error(message);
    }
  };

  const handleDeleteFolder = async () => {
    if (!selectedFolderNode?.spaceId || !selectedFolderNode.deletable) {
      return;
    }
    try {
      const result = await deleteSpaceMutation.mutateAsync(selectedFolderNode.spaceId);
      toast.success(result.message);
      setSelectedFolderPath(`personal:${result.fallback_space_id}`);
    } catch (deleteError) {
      toast.error((deleteError as Error).message ?? "删除文件夹失败");
    }
  };

  const handleMoveFile = async () => {
    if (!movingRecord?.userRecordId || !moveTargetSpaceId) {
      return;
    }
    try {
      const result = await moveUserRecordMutation.mutateAsync({
        recordId: movingRecord.userRecordId,
        knowledgeSpaceId: moveTargetSpaceId,
      });
      toast.success(result.message);
      setMovingRecord(null);
    } catch (moveError) {
      toast.error((moveError as Error).message ?? "移动失败");
    }
  };

  const openEditDialog = (file: KnowledgeFileInfo) => {
    setEditingFile(file);
    setTypeInput(
      KNOWLEDGE_TYPES.has(String(file.type ?? "").toLowerCase())
        ? (String(file.type).toLowerCase() as KnowledgeType)
        : "unknown",
    );
    setFolderInput(file.folder ?? "");
    setCategoriesInput(joinTagInput(file.categories));
    setErasInput(joinTagInput(file.eras));
    setRegionsInput(joinTagInput(file.regions));
    setKeywordsInput(joinTagInput(file.keywords));
    setSummaryInput(file.summary ?? "");
    setLanguageHintInput((file.hints?.language_hint as LanguageHint) ?? "unknown");
    setLayoutHintInput((file.hints?.layout_hint as LayoutHint) ?? "unknown");
    setDocumentTypeHintInput(
      (file.hints?.document_type_hint as DocumentTypeHint) ?? "unknown",
    );
  };

  const closeEditDialog = () => {
    setEditingFile(null);
    setTypeInput("unknown");
    setFolderInput("");
    setCategoriesInput("");
    setErasInput("");
    setRegionsInput("");
    setKeywordsInput("");
    setSummaryInput("");
    setLanguageHintInput("unknown");
    setLayoutHintInput("unknown");
    setDocumentTypeHintInput("unknown");
  };

  const applyMetadataToForm = (metadata: {
    type?: string | null;
    folder?: string | null;
    categories?: string[];
    eras?: string[];
    regions?: string[];
    keywords?: string[];
    summary?: string | null;
    language_hint?: string | null;
    layout_hint?: string | null;
    document_type_hint?: string | null;
  }) => {
    setTypeInput(
      KNOWLEDGE_TYPES.has(String(metadata.type ?? "").toLowerCase())
        ? (String(metadata.type).toLowerCase() as KnowledgeType)
        : "unknown",
    );
    setFolderInput(metadata.folder ?? "");
    setCategoriesInput(joinTagInput(metadata.categories));
    setErasInput(joinTagInput(metadata.eras));
    setRegionsInput(joinTagInput(metadata.regions));
    setKeywordsInput(joinTagInput(metadata.keywords));
    setSummaryInput(metadata.summary ?? "");
    setLanguageHintInput((metadata.language_hint as LanguageHint) ?? "unknown");
    setLayoutHintInput((metadata.layout_hint as LayoutHint) ?? "unknown");
    setDocumentTypeHintInput(
      (metadata.document_type_hint as DocumentTypeHint) ?? "unknown",
    );
  };

  const handleSaveMetadata = async () => {
    if (!editingFile) {
      return;
    }

    try {
      const result = await updateMetadataMutation.mutateAsync({
        filename: editingFile.filename,
        payload: {
          type: typeInput === "unknown" ? null : typeInput,
          folder: folderInput.trim() || null,
          categories: splitTagInput(categoriesInput),
          eras: splitTagInput(erasInput),
          regions: splitTagInput(regionsInput),
          keywords: splitTagInput(keywordsInput),
          summary: summaryInput.trim() || null,
          language_hint:
            languageHintInput === "unknown" ? null : languageHintInput,
          layout_hint: layoutHintInput === "unknown" ? null : layoutHintInput,
          document_type_hint:
            documentTypeHintInput === "unknown" ? null : documentTypeHintInput,
        },
      });
      toast.success(result.message || "标签已更新");
      closeEditDialog();
    } catch (updateError) {
      toast.error((updateError as Error).message || "标签更新失败");
    }
  };

  const handleRegenerateMetadata = async () => {
    if (!editingFile) {
      return;
    }

    try {
      const result = await regenerateMetadataMutation.mutateAsync(editingFile.filename);
      applyMetadataToForm(result.metadata);
      toast.success(result.message || "已重新生成标签");
    } catch (regenerateError) {
      toast.error((regenerateError as Error).message || "AI 生成失败");
    }
  };

  const toggleFileSelection = (rowId: string) => {
    setSelectedRowIds((current) =>
      current.includes(rowId)
        ? current.filter((item) => item !== rowId)
        : [...current, rowId],
    );
  };

  const handleToggleAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedRowIds([]);
      return;
    }
    setSelectedRowIds(
      folderFilteredFiles
        .filter((file) => file.parseStatus === "indexed" && file.docId)
        .map((file) => file.rowId),
    );
  };

  const handleStartChat = () => {
    if (selectedMaterialsPayload.length === 0) {
      toast.error("请先勾选已入库的资料");
      return;
    }

    router.push(
      `/workspace/chats/new?materials=${encodeURIComponent(
        JSON.stringify(selectedMaterialsPayload),
      )}`,
    );
  };

  const handleToggleFolderPath = (path: string) => {
    setExpandedFolderPaths((current) =>
      current.includes(path)
        ? current.filter((item) => item !== path)
        : [...current, path],
    );
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="bg-[linear-gradient(180deg,rgba(247,251,252,1),rgba(241,248,249,1))]">
        <div className="flex h-full w-full min-w-0 flex-1 flex-col px-3 py-3 lg:px-4">
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[rgba(57,130,152,0.16)] bg-white/95 shadow-sm">
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
                if (!open && !uploadMutation.isPending && !uploadUserMutation.isPending) {
                  resetUploadDialog();
                  return;
                }
                setIsUploadDialogOpen(open);
              }}
            >
              <DialogContent className="max-w-2xl border-[rgba(57,130,152,0.16)] bg-[rgb(247,251,252)]/95">
                <DialogHeader>
                  <DialogTitle className="text-slate-900">
                    上传到{uploadTargetMode === "global"
                      ? "系统目录"
                      : (uploadTargetPersonalSpace?.name ?? "个人文件夹")}
                  </DialogTitle>
                  <DialogDescription className="text-slate-600">
                    {uploadTargetMode === "global"
                      ? "当前选择的是系统目录，文件会进入系统知识库。"
                      : "当前选择的是个人目录，文件会进入对应个人文件夹。"}
                  </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4">
                  <div className="rounded-xl border border-[rgba(57,130,152,0.14)] bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          选择文件
                        </div>
                        <div className="text-xs text-slate-500">
                          PDF、Markdown、Office 文档都可以批量上传。
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="border-[rgba(57,130,152,0.18)] bg-white text-[rgb(23,89,108)]"
                        onClick={handlePickFiles}
                        disabled={uploadMutation.isPending || uploadUserMutation.isPending}
                      >
                        选择文件
                      </Button>
                    </div>

                    <div className="mt-3 rounded-lg border border-dashed border-[rgba(57,130,152,0.16)] bg-[rgb(247,251,252)] p-3">
                      {pendingFiles.length === 0 ? (
                        <div className="text-sm text-slate-500">
                          还没有选择文件。
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <div className="text-sm font-medium text-slate-900">
                            已选择 {pendingFiles.length} 个文件
                          </div>
                          <div className="max-h-28 space-y-1 overflow-auto text-xs text-slate-600">
                            {pendingFiles.map((file) => (
                              <div key={`${file.name}-${file.size}`}>{file.name}</div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="grid gap-3 rounded-xl border border-[rgba(57,130,152,0.14)] bg-white p-4 md:grid-cols-3">
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-slate-700">文档类型</div>
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
                      <div className="text-xs font-medium text-slate-700">语言线索</div>
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
                      <div className="text-xs font-medium text-slate-700">版式线索</div>
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
                    className="border-[rgba(57,130,152,0.18)] bg-white text-[rgb(23,89,108)]"
                    onClick={resetUploadDialog}
                    disabled={uploadMutation.isPending || uploadUserMutation.isPending}
                  >
                    取消
                  </Button>
                  <Button
                    type="button"
                    className="bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]"
                    onClick={() => void handleUploadSubmit()}
                    disabled={
                      uploadMutation.isPending ||
                      uploadUserMutation.isPending ||
                      pendingFiles.length === 0
                    }
                  >
                    {uploadMutation.isPending || uploadUserMutation.isPending ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <UploadIcon className="size-4" />
                    )}
                    开始上传
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Dialog open={isCreateFolderDialogOpen} onOpenChange={setIsCreateFolderDialogOpen}>
              <DialogContent className="max-w-md border-[rgba(57,130,152,0.16)] bg-[rgb(247,251,252)]/95">
                <DialogHeader>
                  <DialogTitle className="text-slate-900">新建个人文件夹</DialogTitle>
                  <DialogDescription className="text-slate-600">
                    新文件夹会出现在“个人”顶层目录下。
                  </DialogDescription>
                </DialogHeader>
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">文件夹名称</label>
                  <Input
                    value={newFolderName}
                    onChange={(event) => setNewFolderName(event.target.value)}
                    placeholder="例如：晚清财政"
                    className="bg-white"
                  />
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setIsCreateFolderDialogOpen(false)}
                    disabled={createSpaceMutation.isPending}
                  >
                    取消
                  </Button>
                  <Button
                    type="button"
                    className="bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]"
                    onClick={() => void handleCreateFolder()}
                    disabled={createSpaceMutation.isPending}
                  >
                    {createSpaceMutation.isPending ? <Loader2Icon className="size-4 animate-spin" /> : <PlusIcon className="size-4" />}
                    创建
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Dialog open={Boolean(movingRecord)} onOpenChange={(open) => !open && setMovingRecord(null)}>
              <DialogContent className="max-w-md border-[rgba(57,130,152,0.16)] bg-[rgb(247,251,252)]/95">
                <DialogHeader>
                  <DialogTitle className="text-slate-900">移动文件</DialogTitle>
                  <DialogDescription className="text-slate-600">
                    将个人文件移动到另一个个人文件夹。
                  </DialogDescription>
                </DialogHeader>
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">目标文件夹</label>
                  <Select value={moveTargetSpaceId} onValueChange={setMoveTargetSpaceId}>
                    <SelectTrigger className="bg-white text-sm">
                      <SelectValue placeholder="选择文件夹" />
                    </SelectTrigger>
                    <SelectContent>
                      {personalSpaces.map((space) => (
                        <SelectItem key={space.id} value={space.id}>
                          {space.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setMovingRecord(null)}
                    disabled={moveUserRecordMutation.isPending}
                  >
                    取消
                  </Button>
                  <Button
                    type="button"
                    className="bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]"
                    onClick={() => void handleMoveFile()}
                    disabled={moveUserRecordMutation.isPending || !moveTargetSpaceId}
                  >
                    {moveUserRecordMutation.isPending ? <Loader2Icon className="size-4 animate-spin" /> : <ArrowRightIcon className="size-4" />}
                    移动
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {/* Windows 11 Explorer Style Toolbar (Ribbon) */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-[#f9f9f9] px-2 py-1.5 flex-shrink-0">
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-slate-700 hover:bg-slate-200" onClick={handleOpenUploadDialog} disabled={uploadMutation.isPending || uploadUserMutation.isPending}>
                  {uploadMutation.isPending || uploadUserMutation.isPending ? <Loader2Icon className="size-4 animate-spin text-blue-600" /> : <UploadIcon className="size-4 text-blue-600" />}
                  <span className="text-xs font-medium">新建 / 上传</span>
                </Button>
                <div className="h-4 w-px bg-slate-300 mx-1"></div>
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-slate-700 hover:bg-slate-200" onClick={() => setIsCreateFolderDialogOpen(true)} disabled={createSpaceMutation.isPending}>
                  {createSpaceMutation.isPending ? <Loader2Icon className="size-4 animate-spin text-yellow-500" /> : <FolderIcon className="size-4 text-yellow-500 fill-yellow-100" />}
                  <span className="text-xs font-medium">新建文件夹</span>
                </Button>
                <div className="h-4 w-px bg-slate-300 mx-1"></div>
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-slate-700 hover:bg-slate-200" onClick={handleStartChat} disabled={selectedMaterialsPayload.length === 0}>
                  <BookmarkPlusIcon className="size-4 text-purple-600" />
                  <span className="text-xs font-medium">基于选择项提问</span>
                </Button>
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-slate-700 hover:bg-slate-200" onClick={() => void refetch()} disabled={isFetching}>
                  <RefreshCwIcon className={cn("size-4 text-green-600", isFetching && "animate-spin")} />
                  <span className="text-xs font-medium">刷新</span>
                </Button>
              </div>
              <div className="flex items-center gap-2 pr-2">
                <div className="text-[11px] text-slate-500 flex items-center gap-3">
                  <span className="flex items-center gap-1 select-none">
                    <span className="inline-block size-2 rounded-full bg-blue-500"></span>
                    <span>全部 {summary.total}</span>
                  </span>
                  <span className="flex items-center gap-1 select-none">
                    <span className="inline-block size-2 rounded-full bg-green-500"></span>
                    <span>已入库 {summary.indexed}</span>
                  </span>
                  {summary.active > 0 && (
                    <span className="flex items-center gap-1 select-none animate-pulse">
                      <span className="inline-block size-2 rounded-full bg-yellow-500"></span>
                      <span>处理中 {summary.active}</span>
                    </span>
                  )}
                  {summary.failed > 0 && (
                    <span className="flex items-center gap-1 select-none">
                      <span className="inline-block size-2 rounded-full bg-red-500"></span>
                      <span>失败 {summary.failed}</span>
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Address Bar & Search Box */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2 flex-shrink-0 shadow-sm z-10">
               <div className="flex items-center gap-1 mr-3 shrink-0">
                 <Button 
                   variant="ghost" 
                   size="icon" 
                   className="h-7 w-7 text-slate-500 hover:bg-slate-200" 
                   disabled={selectedFolderPath === "all"}
                   onClick={() => {
                     if (breadcrumbs.length > 1) {
                       setSelectedFolderPath(breadcrumbs[breadcrumbs.length - 2].path);
                     } else {
                       setSelectedFolderPath("all");
                     }
                   }}
                 >
                   <ArrowLeftIcon className="size-4" />
                 </Button>
                 <Button 
                   variant="ghost" 
                   size="icon" 
                   className="h-7 w-7 text-slate-500 hover:bg-slate-200" 
                   disabled={selectedFolderPath === "all"}
                   onClick={() => setSelectedFolderPath("all")}
                   title="返回顶层主页"
                 >
                   <ArrowUpIcon className="size-4" />
                 </Button>
               </div>

               <div className="flex flex-1 items-center gap-2 mr-4 rounded-md border border-slate-200 bg-white px-3 py-1 shadow-inner focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500">
                  <div className="flex items-center gap-1.5 text-xs text-slate-700 select-none w-full truncate">
                    <FolderIcon className="size-4 text-blue-500 fill-blue-50 shrink-0" />
                    <ChevronRightIcon className="size-3.5 text-slate-400 shrink-0" />
                    {breadcrumbs.length === 0 ? (
                      <span className="font-medium text-slate-900 cursor-default px-1">此电脑 (主页)</span>
                    ) : (
                      breadcrumbs.map((bc, i) => (
                        <div key={bc.path} className="flex items-center gap-1.5 shrink-0">
                          {i > 0 && <ChevronRightIcon className="size-3.5 text-slate-400 shrink-0" />}
                          <span 
                            className="cursor-pointer hover:bg-blue-50 hover:text-blue-700 px-1 rounded transition-colors"
                            onClick={() => setSelectedFolderPath(bc.path)}
                          >
                            {bc.name === "系统" ? "此电脑 (系统区)" : bc.name === "个人" ? "主位 (个人区)" : bc.name}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
               </div>
               
               <div className="flex items-center gap-2 shrink-0">
                 <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as FileStatusFilter)}>
                    <SelectTrigger className="h-[28px] w-[110px] bg-white text-xs border-slate-200 text-slate-700 focus:ring-0 focus:ring-offset-0 shadow-inner">
                      <SelectValue placeholder="状态筛选" />
                    </SelectTrigger>
                    <SelectContent className="text-xs">
                      {statusFilterOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value} className="text-xs">
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                 </Select>
                 <div className="relative">
                   <Input
                     value={searchQuery}
                     onChange={(event) => setSearchQuery(event.target.value)}
                     placeholder={`搜索 "${selectedFolderNode?.name ?? "全部文件"}"`}
                     className="h-[28px] w-56 pr-8 text-xs bg-white border-slate-200 focus-visible:ring-blue-500 shadow-inner"
                   />
                   <SearchIcon className="absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400 pointer-events-none" />
                 </div>
               </div>
            </div>



            {isLoading || personalRecordsQuery.isLoading || personalSpacesQuery.isLoading ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center gap-2 text-sm">
                <Loader2Icon className="size-4 animate-spin" />
                正在加载知识库文件列表
              </div>
            ) : error || personalRecordsQuery.error || personalSpacesQuery.error ? (
              <div className="m-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {(error ?? personalRecordsQuery.error ?? personalSpacesQuery.error)?.message}
              </div>
            ) : managedFiles.length === 0 ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center px-6 text-sm">
                还没有知识库文件。
              </div>
            ) : (selectedFolderPath !== "all" && folderFilteredFiles.length === 0 && (!selectedFolderNode?.children || selectedFolderNode.children.length === 0)) ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center px-6 text-sm">
                此文件夹为空。
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 overflow-hidden">
                <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
                  {/* Address bar moved up, omitting local table header */}

                  {folderFilteredFiles.length === 0 ? (
                    <div className="text-muted-foreground flex h-full items-center justify-center px-6 text-sm">
                      没有符合当前目录和筛选条件的文件。
                    </div>
                  ) : (
                    <div className="min-h-0 h-full overflow-auto bg-white pb-10">
                      <Table className="w-full text-[13px] text-slate-700">
                  <TableHeader className="sticky top-0 z-10 bg-white shadow-[0_1px_0_0_rgb(226,232,240)]">
                    <TableRow className="hover:bg-transparent border-none">
                      <TableHead className="w-[48px] px-4 font-normal text-slate-500">
                        <button
                          type="button"
                          className="inline-flex items-center text-slate-400 hover:text-blue-600"
                          onClick={handleToggleAllVisible}
                        >
                          {allVisibleSelected ? (
                            <CheckSquareIcon className="size-4 text-blue-500" />
                          ) : (
                            <SquareIcon className="size-4" />
                          )}
                        </button>
                      </TableHead>
                      <TableHead className="w-[40%] font-normal text-slate-500 border-l border-transparent hover:border-slate-200 px-3 cursor-default hover:bg-slate-50">文件名称</TableHead>
                      <TableHead className="w-[12%] font-normal text-slate-500 border-l border-slate-200 px-3 cursor-default hover:bg-slate-50">状态</TableHead>
                      <TableHead className="w-[16%] font-normal text-slate-500 border-l border-slate-200 px-3 cursor-default hover:bg-slate-50">修改日期</TableHead>
                      <TableHead className="w-[12%] font-normal text-slate-500 border-l border-slate-200 px-3 cursor-default hover:bg-slate-50">类型</TableHead>
                      <TableHead className="w-[10%] font-normal text-slate-500 border-l border-slate-200 px-3 cursor-default hover:bg-slate-50">大小</TableHead>
                      <TableHead className="w-[10%] font-normal text-slate-500 border-l border-slate-200 px-3 cursor-default text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {/* Render Folders First */}
                    {(selectedFolderPath === "all" ? folderTree : selectedFolderNode?.children ?? []).map((folderNode) => (
                      <TableRow 
                          key={`folder-${folderNode.path}`}
                          className="h-10 hover:bg-blue-50/50 transition-colors border-none border-b border-slate-100 cursor-pointer"
                          onDoubleClick={() => setSelectedFolderPath(folderNode.path)}
                      >
                          <TableCell className="w-[48px] px-4 py-1.5"></TableCell>
                          <TableCell className="w-[40%] px-3 py-1.5 truncate">
                            <div className="flex items-center gap-2">
                              <FolderIcon className="size-5 shrink-0 text-yellow-500 fill-yellow-100" />
                              <span className="truncate text-slate-800 font-medium select-none">
                                {folderNode.name === "系统" ? "此电脑 (系统知识库)" : folderNode.name === "个人" ? "个人空间" : folderNode.name}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="w-[12%] px-3 py-1.5 truncate text-[12px]"></TableCell>
                          <TableCell className="w-[16%] px-3 py-1.5 truncate text-[12px] text-slate-400">-</TableCell>
                          <TableCell className="w-[12%] px-3 py-1.5 truncate text-[12px] text-slate-500">文件夹</TableCell>
                          <TableCell className="w-[10%] px-3 py-1.5 truncate text-[12px] text-slate-400">-</TableCell>
                          <TableCell className="w-[10%] px-3 py-1.5 text-right"></TableCell>
                      </TableRow>
                    ))}

                    {/* Then Render Files */}
                    {folderFilteredFiles.map((file) => {
                      const isSelected = selectedRowIds.includes(file.rowId);
                      const canSelectForChat =
                        Boolean(file.docId) && file.parseStatus === "indexed";
                      const readerHref = buildManagedFileReaderHref(file);
                      const canOpenReader =
                        Boolean(readerHref) &&
                        Boolean(file.documentUrl) &&
                        ["indexed", "parsed"].includes(file.parseStatus ?? "");
                      const isDeleting =
                        (file.source === "global" &&
                          deleteMutation.isPending &&
                          deletingFilename === file.filename) ||
                        (file.source === "personal" &&
                          deleteUserRecordMutation.isPending &&
                          deletingRecordId === file.userRecordId);
                      const isRetrying =
                        retryMutation.isPending &&
                        retryingFilename === file.filename;
                      
                      const canRetry =
                        file.source === "global" &&
                        file.indexable &&
                        ["failed", "index_failed", "indexed"].includes(file.parseStatus ?? "");
                      const retryLabel = retryActionLabel(file.parseStatus);
                      const hasEditableMetadataSource =
                        (file.source === "global" &&
                        Boolean(file.structuredFilename)) ||
                        [".md", ".markdown", ".txt"].includes(
                          (file.extension ?? "").toLowerCase(),
                        );
                      const editDisabled =
                        !hasEditableMetadataSource ||
                        ["queued", "queued_ocr", "parsing"].includes(file.parseStatus ?? "");

                      return (
                        <TableRow 
                          key={file.rowId} 
                          className={cn(
                            "h-10 hover:bg-blue-50/50 transition-colors border-none border-b border-slate-100",
                            isSelected && "bg-blue-50/80 hover:bg-blue-100/50"
                          )}
                        >
                          <TableCell className="w-[48px] px-4 py-1.5">
                            <button
                              type="button"
                              className={cn(
                                "inline-flex items-center justify-center",
                                isSelected ? "text-blue-500" : "text-slate-300 hover:text-slate-500"
                              )}
                              onClick={() => toggleFileSelection(file.rowId)}
                              disabled={!canSelectForChat}
                            >
                              {isSelected ? (
                                <CheckSquareIcon className="size-4" />
                              ) : (
                                <SquareIcon className="size-4" />
                              )}
                            </button>
                          </TableCell>
                          <TableCell className="w-[40%] px-3 py-1.5 truncate">
                            <div className="flex items-center gap-2">
                              <FileIcon className={cn("size-4 shrink-0", isSelected ? "text-blue-500" : "text-slate-400 fill-slate-50")} />
                              <div className="min-w-0" title={file.title}>
                                {canOpenReader && readerHref ? (
                                  <a
                                    href={readerHref}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="truncate text-slate-800 hover:text-blue-600 focus:outline-none"
                                  >
                                    {file.title}
                                  </a>
                                ) : (
                                  <span className="truncate text-slate-800">
                                    {file.title}
                                  </span>
                                )}
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="w-[12%] px-3 py-1.5 truncate text-[12px]">
                            {statusLabel(file.parseStatus)}
                          </TableCell>
                          <TableCell className="w-[16%] px-3 py-1.5 truncate text-[12px] text-slate-500">
                            {formatCompactTime(file.modified)}
                          </TableCell>
                          <TableCell className="w-[12%] px-3 py-1.5 truncate text-[12px] text-slate-500">
                            {documentTypeLabel(file.hints?.document_type_hint)}
                          </TableCell>
                          <TableCell className="w-[10%] px-3 py-1.5 truncate text-[12px] text-slate-500">
                            {formatBytes(file.size)}
                          </TableCell>
                          <TableCell className="w-[10%] px-3 py-1.5 text-right">
                            <div className="flex justify-end gap-1">
                              {file.source === "global" ? (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-slate-400 hover:text-slate-700"
                                  disabled={editDisabled || updateMetadataMutation.isPending}
                                  onClick={() =>
                                    openEditDialog(
                                      sortedGlobalFiles.find((candidate) => candidate.filename === file.filename)!,
                                    )
                                  }
                                  title="属性 / 标签"
                                >
                                  <PencilIcon className="size-3.5" />
                                </Button>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-slate-400 hover:text-slate-700"
                                  disabled={personalSpaces.length <= 1}
                                  onClick={() => {
                                    setMovingRecord(file);
                                    setMoveTargetSpaceId(file.knowledgeSpaceId ?? defaultPersonalSpace?.id ?? "");
                                  }}
                                  title="移动到..."
                                >
                                  <FolderIcon className="size-3.5" />
                                </Button>
                              )}
                              {canRetry && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-slate-400 hover:text-slate-700"
                                  disabled={retryMutation.isPending}
                                  onClick={() => void handleRetryIndexing(file.filename)}
                                  title={retryLabel}
                                >
                                  {isRetrying ? (
                                    <Loader2Icon className="size-3.5 animate-spin" />
                                  ) : (
                                    <RefreshCwIcon className="size-3.5" />
                                  )}
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-slate-400 hover:text-red-600"
                                disabled={
                                  file.source === "global"
                                    ? deleteMutation.isPending
                                    : deleteUserRecordMutation.isPending
                                }
                                onClick={() =>
                                  file.source === "global"
                                    ? void handleDelete(file.filename)
                                    : void handleDeletePersonalRecord(file.userRecordId ?? "")
                                }
                                title="删除"
                              >
                                {isDeleting ? (
                                  <Loader2Icon className="size-3.5 animate-spin" />
                                ) : (
                                  <Trash2Icon className="size-3.5" />
                                )}
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>

        <Dialog
          open={Boolean(editingFile)}
          onOpenChange={(open) => {
            if (!open && !updateMetadataMutation.isPending) {
              closeEditDialog();
            }
          }}
        >
          <DialogContent className="max-w-2xl border-[rgba(57,130,152,0.16)] bg-[rgb(247,251,252)]/95">
            <DialogHeader>
              <DialogTitle className="text-slate-900">修改书籍标签</DialogTitle>
              <DialogDescription className="text-slate-600">
                修改的是书级 metadata，会影响书目路由和候选排序，但不会重跑 OCR 或向量化。
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-4">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">检索类型</label>
                  <Select
                    value={typeInput}
                    onValueChange={(value) => setTypeInput(value as KnowledgeType)}
                  >
                    <SelectTrigger className="bg-white text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {knowledgeTypeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">文件夹路径</label>
                  <Input
                    value={folderInput}
                    onChange={(event) => setFolderInput(event.target.value)}
                    placeholder="例如：财政史/清代"
                    className="bg-white"
                  />
                  <p className="text-xs text-slate-500">
                    使用 `/` 表示多级目录；留空时会按首个标签回退归档。
                  </p>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">语言线索</label>
                  <Select
                    value={languageHintInput}
                    onValueChange={(value) => setLanguageHintInput(value as LanguageHint)}
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
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">版式线索</label>
                  <Select
                    value={layoutHintInput}
                    onValueChange={(value) => setLayoutHintInput(value as LayoutHint)}
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

              <div className="grid gap-2">
                <label className="text-sm font-medium text-slate-800">文档类型线索</label>
                <Select
                  value={documentTypeHintInput}
                  onValueChange={(value) =>
                    setDocumentTypeHintInput(value as DocumentTypeHint)
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
                <p className="text-xs text-slate-500">
                  修改线索后不会自动重跑 OCR；保存后可直接点击“重新入库”验证召回效果。
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">分类</label>
                  <Input
                    value={categoriesInput}
                    onChange={(event) => setCategoriesInput(event.target.value)}
                    placeholder="通史, 财政史, 制度史"
                    className="bg-white"
                  />
                </div>
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">时代</label>
                  <Input
                    value={erasInput}
                    onChange={(event) => setErasInput(event.target.value)}
                    placeholder="先秦, 唐宋, 明清"
                    className="bg-white"
                  />
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">地域</label>
                  <Input
                    value={regionsInput}
                    onChange={(event) => setRegionsInput(event.target.value)}
                    placeholder="全国, 江南, 四川"
                    className="bg-white"
                  />
                </div>
                <div className="grid gap-2">
                  <label className="text-sm font-medium text-slate-800">关键词</label>
                  <Input
                    value={keywordsInput}
                    onChange={(event) => setKeywordsInput(event.target.value)}
                    placeholder="赋税, 盐政, 漕运"
                    className="bg-white"
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <label className="text-sm font-medium text-slate-800">摘要</label>
                <Textarea
                  value={summaryInput}
                  onChange={(event) => setSummaryInput(event.target.value)}
                  placeholder="补充这本书的覆盖范围或定位"
                  rows={5}
                  className="bg-white"
                />
              </div>

              {metadataDialogError && (
                <p className="text-sm text-destructive">
                  {metadataDialogError.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                className="border-[rgba(57,130,152,0.18)] bg-white text-[rgb(23,89,108)]"
                onClick={() => void handleRegenerateMetadata()}
                disabled={updateMetadataMutation.isPending || regenerateMetadataMutation.isPending}
              >
                {regenerateMetadataMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : null}
                AI 生成
              </Button>
              <Button
                type="button"
                variant="outline"
                className="border-[rgba(57,130,152,0.18)] bg-white text-[rgb(23,89,108)]"
                onClick={closeEditDialog}
                disabled={updateMetadataMutation.isPending || regenerateMetadataMutation.isPending}
              >
                取消
              </Button>
              <Button
                type="button"
                className="bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]"
                onClick={() => void handleSaveMetadata()}
                disabled={updateMetadataMutation.isPending || regenerateMetadataMutation.isPending}
              >
                {updateMetadataMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : null}
                保存
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
