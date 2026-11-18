"use client";

import { AlertCircleIcon, ChevronRightIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import type { FolderReorganizeEvent, KnowledgeFileInfo } from "@/core/knowledge/api";
import { reorganizeKnowledgeFolders } from "@/core/knowledge/api";
import {
  useCreateKnowledgeFolder,
  useDeleteKnowledgeFolder,
  useDeleteKnowledgeFile,
  useDeleteKnowledgeFileArtifactsOnly,
  useKnowledgeFiles,
  useKnowledgeFolders,
  useReparseKnowledgeFile,
  useRenameKnowledgeFolder,
  useRegenerateKnowledgeFileMetadata,
  useRetryKnowledgeFileIndexing,
  useUpdateKnowledgeFileMetadata,
  useUploadKnowledgeFiles,
} from "@/core/knowledge/hooks";
import {
  useCreateUserKnowledgeFolder,
  useDeleteUserKnowledgeFolder,
  useDeleteUserKnowledgeRecord,
  useDeleteUserKnowledgeRecordArtifactsOnly,
  useMoveUserKnowledgeRecord,
  useReparseUserKnowledgeRecord,
  useRenameUserKnowledgeFolder,
  useRetryUserKnowledgeRecordIndexing,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecords,
} from "@/core/knowledge/user-hooks";

import { KnowledgeBookDetails } from "./knowledge-book-details";
import {
  BatchGenerateSummaryDialog,
  type BatchSummaryResult,
  CreateFolderDialog,
  MetadataDialog,
  MoveFileDialog,
  ReorganizeFolderDialog,
  UploadDialog,
} from "./knowledge-management-page.dialogs";
import {
  KnowledgeEmptyState,
  KnowledgeFileCard,
  KnowledgeManagementSidebar,
  KnowledgeManagementToolbar,
} from "./knowledge-management-page.sections";
import {
  buildScopedFolderTreeFromSummaries,
  buildSystemLibraryTree,
  buildFolderBreadcrumbs,
  buildManagedFileReaderHref,
  buildManagedFiles,
  buildMetadataFormState,
  buildMetadataPayload,
  buildPersonalFolderTree,
  buildSelectedMaterialsPayload,
  createEmptyMetadataFormState,
  createEmptyUploadFormState,
  filterManagedFiles,
  findFolderNode,
  getFolderDisplayName,
  isFileInFolderScope,
  isRepublicFiscalHistoryFile,
  FISCAL_ECONOMY_PATH,
  FISCAL_HISTORY_PATH,
  ORIGINAL_FOLDERS_PATH,
  REPUBLIC_FISCAL_HISTORY_PATH,
  sortGlobalKnowledgeFiles,
  type FolderTreeNode,
  type ManagedKnowledgeFile,
} from "./knowledge-management-page.utils";

const PAGE_SIZE = 24;
const initialExpandedPaths = ["system-root", FISCAL_ECONOMY_PATH, FISCAL_HISTORY_PATH];

export default function KnowledgeManagementPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderContextMenuRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const detailTriggerRef = useRef<HTMLButtonElement>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isCreateFolderDialogOpen, setIsCreateFolderDialogOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState(createEmptyUploadFormState);
  const [searchQuery, setSearchQuery] = useState("");
  const [summaryFilter, setSummaryFilter] = useState("all");
  const [sortOrder, setSortOrder] = useState("recent");
  const [visibleLimit, setVisibleLimit] = useState(PAGE_SIZE);
  const [detailsRowId, setDetailsRowId] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState(initialExpandedPaths);
  const [mobileFoldersOpen, setMobileFoldersOpen] = useState(false);
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);
  const [retryingRowId, setRetryingRowId] = useState<string | null>(null);
  const [reparsingRowId, setReparsingRowId] = useState<string | null>(null);
  const [movingRecord, setMovingRecord] = useState<ManagedKnowledgeFile | null>(null);
  const [moveTargetFolderPath, setMoveTargetFolderPath] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [renamingFolderName, setRenamingFolderName] = useState("");
  const [isRenameFolderDialogOpen, setIsRenameFolderDialogOpen] = useState(false);
  const [folderContextMenu, setFolderContextMenu] = useState<{
    x: number;
    y: number;
    folder: FolderTreeNode;
  } | null>(null);
  const [editingFile, setEditingFile] = useState<KnowledgeFileInfo | null>(null);
  const [metadataForm, setMetadataForm] = useState(createEmptyMetadataFormState);
  const [selectedFolderPath, setSelectedFolderPath] = useState(REPUBLIC_FISCAL_HISTORY_PATH);
  const [isReorganizeDialogOpen, setIsReorganizeDialogOpen] = useState(false);
  const [isReorganizing, setIsReorganizing] = useState(false);
  const [reorganizeEvents, setReorganizeEvents] = useState<FolderReorganizeEvent[]>([]);
  const [isBatchSummaryDialogOpen, setIsBatchSummaryDialogOpen] = useState(false);
  const [isBatchGeneratingSummary, setIsBatchGeneratingSummary] = useState(false);
  const [batchSummaryResults, setBatchSummaryResults] = useState<BatchSummaryResult[]>([]);
  const [batchSummaryTotal, setBatchSummaryTotal] = useState(0);

  const globalFoldersQuery = useKnowledgeFolders();
  const globalFilesQuery = useKnowledgeFiles(undefined, true);
  const personalRecordsQuery = useUserKnowledgeRecords();
  const uploadMutation = useUploadKnowledgeFiles();
  const uploadUserMutation = useUploadUserKnowledgeFiles();
  const createKnowledgeFolderMutation = useCreateKnowledgeFolder();
  const renameKnowledgeFolderMutation = useRenameKnowledgeFolder();
  const deleteKnowledgeFolderMutation = useDeleteKnowledgeFolder();
  const createUserFolderMutation = useCreateUserKnowledgeFolder();
  const renameUserFolderMutation = useRenameUserKnowledgeFolder();
  const deleteUserFolderMutation = useDeleteUserKnowledgeFolder();
  const deleteMutation = useDeleteKnowledgeFile();
  const deleteArtifactsOnlyMutation = useDeleteKnowledgeFileArtifactsOnly();
  const deleteUserRecordMutation = useDeleteUserKnowledgeRecord();
  const deleteUserRecordArtifactsOnlyMutation = useDeleteUserKnowledgeRecordArtifactsOnly();
  const retryMutation = useRetryKnowledgeFileIndexing();
  const reparseMutation = useReparseKnowledgeFile();
  const retryUserRecordMutation = useRetryUserKnowledgeRecordIndexing();
  const reparseUserRecordMutation = useReparseUserKnowledgeRecord();
  const moveUserRecordMutation = useMoveUserKnowledgeRecord();
  const updateMetadataMutation = useUpdateKnowledgeFileMetadata();
  const regenerateMetadataMutation = useRegenerateKnowledgeFileMetadata();
  const metadataDialogError =
    updateMetadataMutation.error ?? regenerateMetadataMutation.error;

  useEffect(() => {
    document.title = "知识库管理 - 财政历史智能知识库";
  }, []);

  useEffect(() => {
    if (!folderContextMenu) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (
        folderContextMenuRef.current &&
        target instanceof Node &&
        !folderContextMenuRef.current.contains(target)
      ) {
        setFolderContextMenu(null);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setFolderContextMenu(null);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [folderContextMenu]);

  const globalFiles = useMemo(
    () => globalFilesQuery.data?.files ?? [],
    [globalFilesQuery.data?.files],
  );
  const personalRecords = useMemo(
    () => personalRecordsQuery.data?.records ?? [],
    [personalRecordsQuery.data?.records],
  );
  const personalFolderPaths = useMemo(
    () => personalRecordsQuery.data?.folders ?? [],
    [personalRecordsQuery.data?.folders],
  );
  const sortedGlobalFiles = useMemo(
    () => sortGlobalKnowledgeFiles(globalFiles),
    [globalFiles],
  );
  const globalFileMap = useMemo(
    () => new Map(sortedGlobalFiles.map((file) => [file.filename, file])),
    [sortedGlobalFiles],
  );

  const managedFiles = useMemo(
    () =>
      buildManagedFiles({
        globalFiles: sortedGlobalFiles,
        personalRecords,
      }),
    [personalRecords, sortedGlobalFiles],
  );

  const systemFolderTree = useMemo(
    () =>
      buildScopedFolderTreeFromSummaries({
        folders: globalFoldersQuery.data?.folders ?? [],
        prefix: "system:",
        source: "global",
      }),
    [globalFoldersQuery.data?.folders],
  );
  const personalFolderTree = useMemo(
    () => buildPersonalFolderTree(managedFiles, personalFolderPaths),
    [managedFiles, personalFolderPaths],
  );
  const pilotFiles = useMemo(() => managedFiles.filter(isRepublicFiscalHistoryFile), [managedFiles]);
  const folderTree = useMemo(
    () => [
      buildSystemLibraryTree(systemFolderTree, globalFiles.length, pilotFiles.length),
      {
        name: "个人知识库",
        path: "personal-root",
        fileCount: managedFiles.filter((file) => file.source === "personal").length,
        children: personalFolderTree,
        source: "personal" as const,
      },
    ],
    [globalFiles.length, managedFiles, personalFolderTree, pilotFiles.length, systemFolderTree],
  );

  useEffect(() => {
    if (selectedFolderPath !== "all" && !findFolderNode(folderTree, selectedFolderPath)) {
      setSelectedFolderPath("all");
    }
  }, [folderTree, selectedFolderPath]);

  const scopedFilteredFiles = useMemo(
    () => {
      if ([FISCAL_ECONOMY_PATH, FISCAL_HISTORY_PATH, REPUBLIC_FISCAL_HISTORY_PATH].includes(selectedFolderPath)) {
        return pilotFiles;
      }
      const folderPath = selectedFolderPath === ORIGINAL_FOLDERS_PATH ? "system-root" : selectedFolderPath;
      return managedFiles.filter((file) => isFileInFolderScope(file, folderPath));
    },
    [managedFiles, pilotFiles, selectedFolderPath],
  );
  const folderFilteredFiles = useMemo(() => {
    const results = filterManagedFiles({ files: scopedFilteredFiles, searchQuery }).filter((file) =>
      summaryFilter === "all" || Boolean(file.summary?.trim()) === (summaryFilter === "available"),
    );
    return sortOrder === "title" ? results.sort((a, b) => a.title.localeCompare(b.title, "zh-CN")) : results;
  }, [scopedFilteredFiles, searchQuery, sortOrder, summaryFilter]);

  useEffect(() => {
    setVisibleLimit(PAGE_SIZE);
    resultsRef.current?.scrollTo({ top: 0 });
  }, [searchQuery, selectedFolderPath, sortOrder, summaryFilter]);

  useEffect(() => {
    const visibleRowIds = new Set(folderFilteredFiles.map((file) => file.rowId));
    setSelectedRowIds((current) => current.filter((rowId) => visibleRowIds.has(rowId)));
  }, [folderFilteredFiles]);

  const selectedFiles = useMemo(
    () => folderFilteredFiles.filter((file) => selectedRowIds.includes(file.rowId)),
    [folderFilteredFiles, selectedRowIds],
  );
  const selectableVisibleFiles = folderFilteredFiles;
  const allVisibleSelected =
    selectableVisibleFiles.length > 0 &&
    selectedFiles.length === selectableVisibleFiles.length;
  const selectedMaterialsPayload = useMemo(
    () => buildSelectedMaterialsPayload(selectedFiles),
    [selectedFiles],
  );

  const uploadTargetMode =
    selectedFolderPath === "system-root" || selectedFolderPath.startsWith("system:") || selectedFolderPath.startsWith("collection:")
      ? "global"
      : "personal";
  const selectedFolderNode = useMemo(
    () => findFolderNode(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const selectedLogicalFolderPath = useMemo(() => {
    if (selectedFolderPath.startsWith("system:")) {
      return selectedFolderPath.slice("system:".length);
    }
    if (selectedFolderPath.startsWith("personal:")) {
      return selectedFolderPath.slice("personal:".length);
    }
    if (selectedFolderPath === REPUBLIC_FISCAL_HISTORY_PATH) {
      return "民国财政史";
    }
    return "";
  }, [selectedFolderPath]);
  const uploadTargetFolderPath = selectedLogicalFolderPath || null;
  const selectedFolderScope = uploadTargetMode;
  const uploadTargetFolderLabel = selectedFolderNode
    ? getFolderDisplayName(selectedFolderNode.name)
    : uploadTargetMode === "global"
      ? "系统根目录"
      : "个人根目录";
  const breadcrumbs = useMemo(
    () => buildFolderBreadcrumbs(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const detailsFile = managedFiles.find((file) => file.rowId === detailsRowId) ?? null;

  const selectFolder = (path: string) => {
    const ancestors = buildFolderBreadcrumbs(folderTree, path).slice(0, -1).map((item) => item.path);
    setExpandedPaths((current) => [...new Set([...current, ...ancestors])]);
    setSelectedFolderPath(path);
    setMobileFoldersOpen(false);
  };

  const clearFilters = () => {
    setSearchQuery("");
    setSummaryFilter("all");
  };

  const folderNavigation = {
    folders: folderTree,
    count: managedFiles.length,
    selectedPath: selectedFolderPath,
    expandedPaths,
    onSelect: selectFolder,
    onToggle: (path: string) => setExpandedPaths((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
    ),
  };

  const openFolderContextMenu = (
    folder: FolderTreeNode,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setFolderContextMenu({
      x: event.clientX,
      y: event.clientY,
      folder,
    });
  };

  const resetUploadDialog = () => {
    setUploadForm(createEmptyUploadFormState());
    setIsUploadDialogOpen(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleFilesSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setUploadForm((current) => ({ ...current, files }));
    event.target.value = "";
  };

  const handleUploadSubmit = async () => {
    if (uploadForm.files.length === 0) {
      toast.error("请先选择要上传的文件");
      return;
    }

    try {
      const uploadOptions = {
        languageHint: uploadForm.languageHint === "unknown" ? undefined : uploadForm.languageHint,
        layoutHint: uploadForm.layoutHint === "unknown" ? undefined : uploadForm.layoutHint,
        documentTypeHint:
          uploadForm.documentTypeHint === "unknown" ? undefined : uploadForm.documentTypeHint,
      };

      const result =
        uploadTargetMode === "global"
          ? await uploadMutation.mutateAsync({
              files: uploadForm.files,
              options: {
                ...uploadOptions,
                folderPath: uploadTargetFolderPath,
              },
            })
          : await uploadUserMutation.mutateAsync({
              files: uploadForm.files,
              options: {
                ...uploadOptions,
                folderPath: uploadTargetFolderPath,
              },
            });

      toast.success(result.message);
      resetUploadDialog();
      await handleRefresh();
    } catch (uploadError) {
      toast.error(uploadError instanceof Error ? uploadError.message : "上传失败");
    }
  };

  const handleDelete = async (filename: string) => {
    setDeletingFilename(filename);
    try {
      const result = await deleteMutation.mutateAsync(filename);
      toast.success(result.message);
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除失败");
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
      toast.error(deleteError instanceof Error ? deleteError.message : "删除失败");
    } finally {
      setDeletingRecordId(null);
    }
  };

  // Active processing statuses — files in these states cannot be deleted at all.
  const ACTIVE_STATUSES = new Set(["queued", "queued_ocr", "parsing", "queued_embedding", "indexing"]);

  const handleBatchDelete = async () => {
    if (selectedFiles.length === 0) return;
    const confirmed = window.confirm(`确定要删除选中的 ${selectedFiles.length} 份档案吗？此操作不可撤销。`);
    if (!confirmed) return;

    setIsBatchDeleting(true);
    let successCount = 0;
    let failCount = 0;
    let skippedCount = 0;

    for (const file of selectedFiles) {
      const status = file.parseStatus ?? "";

      // Skip files that are currently being processed — deleting them mid-flight is unsafe.
      if (ACTIVE_STATUSES.has(status)) {
        skippedCount++;
        continue;
      }

      try {
        if (status === "indexed") {
          // File is in the vector index → must go through the full delete path so the
          // Qdrant index is updated accordingly.
          if (file.source === "global") {
            await deleteMutation.mutateAsync(file.filename);
          } else {
            await deleteUserRecordMutation.mutateAsync(file.userRecordId ?? "");
          }
        } else {
          // File is only uploaded / parsed / failed → skip the vector DB entirely and
          // just remove the physical files (.book-metadata, .ingestion record, PDF).
          if (file.source === "global") {
            await deleteArtifactsOnlyMutation.mutateAsync(file.filename);
          } else {
            await deleteUserRecordArtifactsOnlyMutation.mutateAsync(file.userRecordId ?? "");
          }
        }
        successCount++;
      } catch {
        failCount++;
      }
    }

    setIsBatchDeleting(false);
    setSelectedRowIds([]);

    if (skippedCount > 0 && failCount === 0) {
      toast.success(`已删除 ${successCount} 份档案，${skippedCount} 份正在处理中已跳过`);
    } else if (failCount === 0) {
      toast.success(`已删除 ${successCount} 份档案`);
    } else {
      toast.warning(`成功删除 ${successCount} 份，${failCount} 份删除失败${skippedCount > 0 ? `，${skippedCount} 份跳过` : ""}`);
    }
  };

  const handleRetryIndexing = async (file: ManagedKnowledgeFile) => {
    setRetryingRowId(file.rowId);
    try {
      const result =
        file.source === "global"
          ? await retryMutation.mutateAsync(file.filename)
          : await retryUserRecordMutation.mutateAsync(file.userRecordId ?? "");
      toast.success(result.message);
    } catch (retryError) {
      toast.error(retryError instanceof Error ? retryError.message : "重新入库失败");
    } finally {
      setRetryingRowId(null);
    }
  };

  const handleReparse = async (file: ManagedKnowledgeFile) => {
    setReparsingRowId(file.rowId);
    try {
      const result =
        file.source === "global"
          ? await reparseMutation.mutateAsync(file.filename)
          : await reparseUserRecordMutation.mutateAsync(file.userRecordId ?? "");
      toast.success(result.message);
    } catch (reparseError) {
      toast.error(reparseError instanceof Error ? reparseError.message : "重新解析失败");
    } finally {
      setReparsingRowId(null);
    }
  };

  const handleCreateFolder = async () => {
    const trimmedName = newFolderName.trim();
    if (!trimmedName) {
      toast.error("请输入文件夹名称");
      return;
    }
    const nextPath = selectedLogicalFolderPath
      ? `${selectedLogicalFolderPath}/${trimmedName}`
      : trimmedName;
    try {
      const result =
        selectedFolderScope === "global"
          ? await createKnowledgeFolderMutation.mutateAsync(nextPath)
          : await createUserFolderMutation.mutateAsync(nextPath);
      toast.success(result.message);
      setNewFolderName("");
      setIsCreateFolderDialogOpen(false);
      // Refresh first so folderTree has the new path before we navigate into it,
      // otherwise the "invalid path" useEffect would immediately reset back to "all".
      await handleRefresh();
      setSelectedFolderPath(
        selectedFolderScope === "global" ? `system:${nextPath}` : `personal:${nextPath}`,
      );
      const parts = nextPath.split("/");
      setExpandedPaths((current) => [...new Set([
        ...current,
        ...(selectedFolderScope === "global" ? ["system-root", ORIGINAL_FOLDERS_PATH] : ["personal-root"]),
        ...parts.slice(0, -1).map((_, index) => `${selectedFolderScope === "global" ? "system" : "personal"}:${parts.slice(0, index + 1).join("/")}`),
      ])]);
    } catch (createError) {
      toast.error(createError instanceof Error ? createError.message : "创建文件夹失败");
    }
  };

  const handleMoveFile = async () => {
    if (!movingRecord?.userRecordId || !moveTargetFolderPath) {
      return;
    }
    try {
      const result = await moveUserRecordMutation.mutateAsync({
        recordId: movingRecord.userRecordId,
        folderPath: moveTargetFolderPath,
      });
      toast.success(result.message);
      setMovingRecord(null);
      setMoveTargetFolderPath("");
    } catch (moveError) {
      toast.error(moveError instanceof Error ? moveError.message : "移动失败");
    }
  };

  const handleRenameFolder = async () => {
    const trimmedName = renamingFolderName.trim();
    if (!selectedLogicalFolderPath || !trimmedName) {
      toast.error("请输入文件夹名称");
      return;
    }
    const parentPath = selectedLogicalFolderPath.includes("/")
      ? selectedLogicalFolderPath.split("/").slice(0, -1).join("/")
      : "";
    const newPath = parentPath ? `${parentPath}/${trimmedName}` : trimmedName;
    try {
      const result =
        selectedFolderScope === "global"
          ? await renameKnowledgeFolderMutation.mutateAsync({
              path: selectedLogicalFolderPath,
              newPath,
            })
          : await renameUserFolderMutation.mutateAsync({
              path: selectedLogicalFolderPath,
              newPath,
            });
      toast.success(result.message);
      setIsRenameFolderDialogOpen(false);
      setRenamingFolderName("");
      // Refresh before navigating so the renamed path already exists in folderTree.
      await handleRefresh();
      setSelectedFolderPath(
        selectedFolderScope === "global" ? `system:${newPath}` : `personal:${newPath}`,
      );
    } catch (renameError) {
      toast.error(renameError instanceof Error ? renameError.message : "重命名失败");
    }
  };

  const openRenameFolder = (folder: FolderTreeNode) => {
    selectFolder(folder.path);
    setRenamingFolderName(folder.name);
    setIsRenameFolderDialogOpen(true);
    setFolderContextMenu(null);
  };

  const handleDeleteFolder = async (folder: FolderTreeNode) => {
    setFolderContextMenu(null);
    if (!window.confirm(`确定删除文件夹「${folder.name}」吗？`)) return;
    const logicalPath = folder.path.replace(/^(system:|personal:)/, "");
    try {
      const result =
        folder.path.startsWith("system:")
          ? await deleteKnowledgeFolderMutation.mutateAsync(logicalPath)
          : await deleteUserFolderMutation.mutateAsync(logicalPath);
      toast.success(result.message);
      setSelectedFolderPath(
        folder.path.startsWith("system:") ? "system-root" : "personal-root",
      );
      await handleRefresh();
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除文件夹失败");
    }
  };

  const renderFolderContextMenu = () => {
    if (!folderContextMenu) {
      return null;
    }
    const menuWidth = 148;
    const left =
      typeof window !== "undefined"
        ? Math.min(folderContextMenu.x, window.innerWidth - menuWidth - 12)
        : folderContextMenu.x;
    const top =
      typeof window !== "undefined"
        ? Math.min(folderContextMenu.y, window.innerHeight - 96)
        : folderContextMenu.y;

    return (
      <div
        ref={folderContextMenuRef}
        className="fixed z-50 rounded-2xl border border-stone-200 bg-white p-1.5 shadow-[0_18px_40px_-22px_rgba(28,25,23,0.4)]"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="flex h-9 w-full items-center rounded-xl px-3 text-sm text-stone-800 transition hover:bg-stone-100"
          onClick={() => openRenameFolder(folderContextMenu.folder)}
        >
          重命名文件夹
        </button>
        <button
          type="button"
          className="flex h-9 w-full items-center rounded-xl px-3 text-sm text-red-700 transition hover:bg-red-50"
          onClick={() => void handleDeleteFolder(folderContextMenu.folder)}
        >
          删除文件夹
        </button>
      </div>
    );
  };

  const openEditDialog = (file: KnowledgeFileInfo) => {
    setEditingFile(file);
    setMetadataForm(buildMetadataFormState(file));
  };

  const closeEditDialog = () => {
    setEditingFile(null);
    setMetadataForm(createEmptyMetadataFormState());
  };

  const handleSaveMetadata = async () => {
    if (!editingFile) {
      return;
    }
    try {
      const result = await updateMetadataMutation.mutateAsync({
        filename: editingFile.filename,
        payload: buildMetadataPayload(metadataForm),
      });
      toast.success(result.message || "标签已更新");
      closeEditDialog();
    } catch (updateError) {
      toast.error(updateError instanceof Error ? updateError.message : "标签更新失败");
    }
  };

  const handleRegenerateMetadata = async () => {
    if (!editingFile) {
      return;
    }
    try {
      const result = await regenerateMetadataMutation.mutateAsync(editingFile.filename);
      setMetadataForm(buildMetadataFormState(result.metadata));
      toast.success(result.message || "已重新生成标签");
    } catch (regenerateError) {
      toast.error(regenerateError instanceof Error ? regenerateError.message : "AI 生成失败");
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
    setSelectedRowIds(selectableVisibleFiles.map((file) => file.rowId));
  };

  const handleStartChat = () => {
    if (selectedMaterialsPayload.length === 0) {
      toast.error("请先勾选已解析的资料");
      return;
    }

    const key = `selected_materials_${Date.now()}`;
    sessionStorage.setItem(key, JSON.stringify(selectedMaterialsPayload));
    router.push(`/workspace/chats/new?materials_key=${encodeURIComponent(key)}`);
  };

  const isLoading = globalFilesQuery.isLoading || globalFoldersQuery.isLoading || personalRecordsQuery.isLoading;
  const error = globalFilesQuery.error ?? globalFoldersQuery.error ?? personalRecordsQuery.error;
  const isUploadPending = uploadMutation.isPending || uploadUserMutation.isPending;
  const isRefreshing = globalFilesQuery.isFetching || globalFoldersQuery.isFetching || personalRecordsQuery.isFetching;

  const handleRefresh = async () => {
    await Promise.all([
      globalFoldersQuery.refetch(),
      globalFilesQuery.refetch(),
      personalRecordsQuery.refetch(),
    ]);
  };

  const handleReorganize = async () => {
    setReorganizeEvents([]);
    setIsReorganizeDialogOpen(true);
    setIsReorganizing(true);
    try {
      for await (const event of reorganizeKnowledgeFolders()) {
        setReorganizeEvents((prev) => [...prev, event]);
      }
    } catch (err) {
      setReorganizeEvents((prev) => [
        ...prev,
        { type: "error", message: String(err) },
      ]);
    } finally {
      setIsReorganizing(false);
      // Refresh the folder list so changes are visible immediately after close.
      void handleRefresh();
    }
  };

  const noSummaryFiles = useMemo(
    () =>
      managedFiles.filter(
        (file) => file.source === "global" && !file.summary?.trim(),
      ),
    [managedFiles],
  );

  const handleBatchGenerateSummary = async () => {
    if (noSummaryFiles.length === 0) return;
    setBatchSummaryResults([]);
    setBatchSummaryTotal(noSummaryFiles.length);
    setIsBatchSummaryDialogOpen(true);
    setIsBatchGeneratingSummary(true);

    for (const file of noSummaryFiles) {
      let lastErr: unknown;
      let succeeded = false;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await regenerateMetadataMutation.mutateAsync(file.filename);
          succeeded = true;
          break;
        } catch (err) {
          lastErr = err;
        }
      }
      if (succeeded) {
        setBatchSummaryResults((prev) => [
          ...prev,
          { filename: file.filename, title: file.title, success: true },
        ]);
      } else {
        setBatchSummaryResults((prev) => [
          ...prev,
          {
            filename: file.filename,
            title: file.title,
            success: false,
            error: lastErr instanceof Error ? lastErr.message : "生成失败",
          },
        ]);
      }
    }

    setIsBatchGeneratingSummary(false);
    void handleRefresh();
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader className="border-b border-primary/5" />
      <WorkspaceBody className="bg-transparent">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFilesSelected}
        />

        <UploadDialog
          open={isUploadDialogOpen}
          onOpenChange={(open) => {
            if (!open && !isUploadPending) {
              resetUploadDialog();
              return;
            }
            setIsUploadDialogOpen(open);
          }}
          form={uploadForm}
          setForm={setUploadForm}
          targetMode={uploadTargetMode}
          targetFolderLabel={uploadTargetFolderLabel}
          onPickFiles={() => fileInputRef.current?.click()}
          onCancel={resetUploadDialog}
          onSubmit={() => void handleUploadSubmit()}
          isPending={isUploadPending}
        />

        <CreateFolderDialog
          open={isCreateFolderDialogOpen}
          onOpenChange={setIsCreateFolderDialogOpen}
          title={`新建${selectedFolderScope === "global" ? "系统" : "个人"}文件夹`}
          description={
            selectedLogicalFolderPath
              ? `新文件夹会创建在“${getFolderDisplayName(selectedLogicalFolderPath)}”下。`
              : `新文件夹会创建在${selectedFolderScope === "global" ? "系统" : "个人"}根目录下。`
          }
          value={newFolderName}
          onValueChange={setNewFolderName}
          onSubmit={() => void handleCreateFolder()}
          isPending={
            createKnowledgeFolderMutation.isPending || createUserFolderMutation.isPending
          }
        />

        <CreateFolderDialog
          open={isRenameFolderDialogOpen}
          onOpenChange={(open) => {
            setIsRenameFolderDialogOpen(open);
            if (!open) {
              setRenamingFolderName("");
            }
          }}
          title="重命名文件夹"
          description="只修改当前文件夹名称，子文件夹层级会一并保留。"
          value={renamingFolderName}
          onValueChange={setRenamingFolderName}
          onSubmit={() => void handleRenameFolder()}
          isPending={
            renameKnowledgeFolderMutation.isPending || renameUserFolderMutation.isPending
          }
        />

        <MoveFileDialog
          open={Boolean(movingRecord)}
          onOpenChange={(open) => {
            if (!open) {
              setMovingRecord(null);
              setMoveTargetFolderPath("");
            }
          }}
          folders={personalFolderPaths}
          value={moveTargetFolderPath}
          onValueChange={setMoveTargetFolderPath}
          onSubmit={() => void handleMoveFile()}
          isPending={moveUserRecordMutation.isPending}
        />

        <MetadataDialog
          open={Boolean(editingFile)}
          onOpenChange={(open) => {
            if (!open && !updateMetadataMutation.isPending) {
              closeEditDialog();
            }
          }}
          form={metadataForm}
          setForm={setMetadataForm}
          errorMessage={metadataDialogError?.message}
          isSaving={updateMetadataMutation.isPending}
          isRegenerating={regenerateMetadataMutation.isPending}
          onRegenerate={() => void handleRegenerateMetadata()}
          onCancel={closeEditDialog}
          onSave={() => void handleSaveMetadata()}
        />

        <div className="flex h-full min-h-0 w-full min-w-0 flex-1 bg-[#faf7ef]">
          <aside className="hidden w-[252px] shrink-0 flex-col border-r border-[#e9e0d3] bg-[#f6f1e7] lg:flex">
            <h2 className="px-7 pt-6 pb-4 font-serif text-lg font-semibold text-[#3b2e23]">馆藏分类</h2>
            <KnowledgeManagementSidebar {...folderNavigation} onContextMenu={openFolderContextMenu} />
          </aside>
          <Sheet open={mobileFoldersOpen} onOpenChange={setMobileFoldersOpen}>
            <SheetContent side="left" className="w-[min(320px,90vw)] gap-2 bg-[#f6f1e7]">
              <SheetTitle className="px-7 pt-5 font-serif text-xl">馆藏分类</SheetTitle>
              <SheetDescription className="sr-only">选择要浏览的目录</SheetDescription>
              <KnowledgeManagementSidebar {...folderNavigation} />
            </SheetContent>
          </Sheet>

          <div className="flex min-w-0 flex-1 flex-col">
            <KnowledgeManagementToolbar
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              onOpenFolders={() => setMobileFoldersOpen(true)}
              onOpenUpload={() => setIsUploadDialogOpen(true)}
              onOpenCreateFolder={() => setIsCreateFolderDialogOpen(true)}
              onRenameFolder={selectedFolderNode?.deletable ? () => openRenameFolder(selectedFolderNode) : undefined}
              onDeleteFolder={selectedFolderNode?.deletable ? () => void handleDeleteFolder(selectedFolderNode) : undefined}
              onOpenReorganize={() => void handleReorganize()}
              onOpenBatchGenerateSummary={noSummaryFiles.length > 0 ? () => void handleBatchGenerateSummary() : undefined}
              onRefresh={() => void handleRefresh()}
              isRefreshing={isRefreshing}
            />

            <div ref={resultsRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <div className="mx-auto w-full max-w-[1520px] px-4 pt-5 pb-12 sm:px-7 sm:pt-7 2xl:px-10">
                {breadcrumbs.length > 0 && (
                  <nav aria-label="当前分类路径" className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#756859]">
                    {breadcrumbs.map((item, index) => (
                      <React.Fragment key={item.path}>
                        {index > 0 && <ChevronRightIcon className="size-3 text-[#a59076]" />}
                        {item.path === selectedFolderPath ? (
                          <span aria-current="page" className="font-semibold text-[#793b32]">{item.name}</span>
                        ) : (
                          <button type="button" onClick={() => selectFolder(item.path)} className="cursor-pointer rounded hover:text-[#793b32] hover:underline">
                            {item.name}
                          </button>
                        )}
                      </React.Fragment>
                    ))}
                  </nav>
                )}
                <h1 className="font-serif text-[30px] leading-tight font-semibold tracking-tight text-[#34261f] sm:text-4xl">
                  {selectedFolderNode?.name ?? "全部馆藏"}
                </h1>
                {selectedFolderPath === REPUBLIC_FISCAL_HISTORY_PATH && (
                  <p className="mt-3 max-w-2xl text-sm leading-7 text-[#685849]">
                    收录民国时期财政制度及其运行相关的资料，可查阅税收、公债、财政收支和地方财政等主题。
                  </p>
                )}

                <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-y border-[#e9e0d3] py-2.5">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-[#685849]" aria-live="polite">
                    <span className="font-medium text-[#49392d]">{isLoading ? "正在读取馆藏" : `${folderFilteredFiles.length} 份资料`}</span>
                    {scopedFilteredFiles.length !== folderFilteredFiles.length && <span className="text-xs">共 {scopedFilteredFiles.length} 份</span>}
                    {selectedFolderNode && selectedFolderNode.children.length > 0 && <span className="text-xs">含子目录</span>}
                    {selectedFolderPath !== "all" && searchQuery.trim() && (
                      <button type="button" onClick={() => selectFolder("all")} className="cursor-pointer rounded text-xs font-medium text-[#793b32] hover:underline">
                        搜索全部馆藏
                      </button>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select aria-label="摘要筛选" value={summaryFilter} onChange={(event) => setSummaryFilter(event.target.value)} className="h-8 rounded-md border border-[#e7ded1] bg-[#fffefa] px-2 text-xs text-[#594a3a]">
                      <option value="all">全部摘要状态</option>
                      <option value="available">有摘要</option>
                      <option value="missing">无摘要</option>
                    </select>
                    <select aria-label="排序" value={sortOrder} onChange={(event) => setSortOrder(event.target.value)} className="h-8 rounded-md border border-[#e7ded1] bg-[#fffefa] px-2 text-xs text-[#594a3a]">
                      <option value="recent">按最近更新</option>
                      <option value="title">按书名</option>
                    </select>
                  </div>
                </div>

                {isLoading && (
                  <div role="status" className="flex items-center justify-center gap-2 py-14 text-sm text-[#685849]">
                    <Loader2Icon className="size-4 animate-spin text-[#793b32]" /> 正在加载资料
                  </div>
                )}
                {!isLoading && error && (
                  <div role="alert" className="mt-5 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                    <AlertCircleIcon className="size-4 shrink-0" /> {error.message}
                    <Button size="sm" variant="link" onClick={() => void handleRefresh()}>重试</Button>
                  </div>
                )}

                {!isLoading && folderFilteredFiles.length > 0 && (
                  <>
                    <div className="mt-4 flex min-h-8 flex-wrap items-center justify-between gap-2 text-xs text-[#685849]">
                      <label className="inline-flex cursor-pointer items-center gap-2">
                        <input type="checkbox" checked={allVisibleSelected} onChange={handleToggleAllVisible} className="size-4 accent-[#793b32]" />
                        全选结果
                      </label>
                      {selectedRowIds.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                          <span>已选 {selectedRowIds.length} 份</span>
                          <Button type="button" size="sm" variant="secondary" onClick={handleStartChat}>选中提问</Button>
                          <Button type="button" size="sm" variant="ghost" onClick={() => void handleBatchDelete()} disabled={isBatchDeleting} className="text-red-700 hover:bg-red-50 hover:text-red-800">
                            {isBatchDeleting ? "正在删除" : "批量删除"}
                          </Button>
                        </div>
                      )}
                    </div>
                    <div className="@container mt-3">
                      <div className="grid grid-cols-1 gap-4 @min-[640px]:grid-cols-2 @min-[1120px]:grid-cols-3">
                        {folderFilteredFiles.slice(0, visibleLimit).map((file) => {
                          const sourceFile = globalFileMap.get(file.filename);
                          const isDeleting =
                            (file.source === "global" && deleteMutation.isPending && deletingFilename === file.filename) ||
                            (file.source === "personal" && deleteUserRecordMutation.isPending && deletingRecordId === file.userRecordId);
                          const isRetrying = file.source === "global" ? retryMutation.isPending : retryUserRecordMutation.isPending;
                          const isReparsing = file.source === "global" ? reparseMutation.isPending : reparseUserRecordMutation.isPending;

                          return (
                            <KnowledgeFileCard
                              key={file.rowId}
                              file={file}
                              isSelected={selectedRowIds.includes(file.rowId)}
                              onToggleSelection={() => toggleFileSelection(file.rowId)}
                              onOpenDetails={(trigger) => {
                                detailTriggerRef.current = trigger;
                                setDetailsRowId(file.rowId);
                              }}
                              onOpenMetadata={() => sourceFile && openEditDialog(sourceFile)}
                              onMoveFile={() => {
                                setMovingRecord(file);
                                setMoveTargetFolderPath(file.folderDisplay);
                              }}
                              onRetry={() => void handleRetryIndexing(file)}
                              onReparse={() => void handleReparse(file)}
                              onDelete={() =>
                                file.source === "global"
                                  ? void handleDelete(file.filename)
                                  : void handleDeletePersonalRecord(file.userRecordId ?? "")
                              }
                              readerHref={buildManagedFileReaderHref(file)}
                              personalSpacesCount={personalFolderPaths.length}
                              isDeleting={isDeleting}
                              isRetrying={isRetrying && retryingRowId === file.rowId}
                              isReparsing={isReparsing && reparsingRowId === file.rowId}
                            />
                          );
                        })}
                      </div>
                    </div>
                    {folderFilteredFiles.length > visibleLimit && (
                      <div className="mt-6 flex justify-center">
                        <Button type="button" variant="outline" onClick={() => setVisibleLimit((current) => current + PAGE_SIZE)}>加载更多资料</Button>
                      </div>
                    )}
                  </>
                )}
                {!isLoading && !error && folderFilteredFiles.length === 0 && (
                  <div className="mt-5">
                    <KnowledgeEmptyState onClear={searchQuery.trim() || summaryFilter !== "all" ? clearFilters : undefined} />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <KnowledgeBookDetails file={detailsFile} onClose={() => setDetailsRowId(null)} restoreFocus={() => detailTriggerRef.current?.focus()} />
        <ReorganizeFolderDialog
          open={isReorganizeDialogOpen}
          onOpenChange={setIsReorganizeDialogOpen}
          events={reorganizeEvents}
          isRunning={isReorganizing}
        />
        <BatchGenerateSummaryDialog
          open={isBatchSummaryDialogOpen}
          onOpenChange={setIsBatchSummaryDialogOpen}
          results={batchSummaryResults}
          total={batchSummaryTotal}
          isRunning={isBatchGeneratingSummary}
        />
      </WorkspaceBody>
      {renderFolderContextMenu()}
    </WorkspaceContainer>
  );
}
