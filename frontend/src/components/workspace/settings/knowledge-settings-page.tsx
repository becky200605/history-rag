"use client";

import { BookOpenIcon, RefreshCwIcon, Trash2Icon, UploadIcon, XIcon } from "lucide-react";
import { useMemo, useRef, useState, type ChangeEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { shouldUseChunkedUpload } from "@/core/knowledge/chunked-upload";
import {
  useKnowledgeStatus,
  useKnowledgeFiles,
  useKnowledgeDocuments,
  useReindexKnowledgeBase,
  useSmartUploadKnowledgeDocument,
  useDeleteKnowledgeDocument,
} from "@/core/knowledge/hooks";

import { SettingsSection } from "./settings-section";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function KnowledgeSettingsPage() {
  const { t } = useI18n();
  const { status, isLoading, error } = useKnowledgeStatus();
  const { data: knowledgeFilesData } = useKnowledgeFiles();
  const { docs, isLoading: isDocsLoading, error: docsError } =
    useKnowledgeDocuments();
  const reindexMutation = useReindexKnowledgeBase();
  const {
    upload,
    cancel: cancelUpload,
    reset: resetUpload,
    isUploading,
    uploadProgress,
    error: uploadError,
  } = useSmartUploadKnowledgeDocument();
  const deleteMutation = useDeleteKnowledgeDocument();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [autoReindex, setAutoReindex] = useState(true);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const statusDescription = useMemo(() => {
    if (!status) return "";
    if (!status.enabled) {
      return t.settings.knowledge.status.disabled;
    }
    return t.settings.knowledge.status.enabled;
  }, [
    status,
    t.settings.knowledge.status.disabled,
    t.settings.knowledge.status.enabled,
  ]);

  const isLargeFile = useMemo(() => {
    return selectedFile ? shouldUseChunkedUpload(selectedFile) : false;
  }, [selectedFile]);

  const hasActiveKnowledgeJobs = useMemo(() => {
    const files = knowledgeFilesData?.files ?? [];
    return files.some((file) =>
      ["queued", "parsing", "indexing"].includes(file.parse_status ?? ""),
    );
  }, [knowledgeFilesData]);

  const isKnowledgeMutating =
    isUploading ||
    deleteMutation.isPending ||
    reindexMutation.isPending ||
    hasActiveKnowledgeJobs;

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadSuccess(false);
    resetUpload();
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploadSuccess(false);
    try {
      await upload(selectedFile, { reindex: autoReindex });
      setSelectedFile(null);
      setUploadSuccess(true);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch {
      // Error is handled by the hook
    }
  };

  const handleCancelUpload = () => {
    cancelUpload();
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.knowledge.title}
        description={t.settings.knowledge.description}
      >
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div>Error: {error.message}</div>
        ) : (
          status && (
            <Item variant="outline" className="w-full">
              <ItemContent>
                <ItemTitle>
                  <div className="flex items-center gap-2">
                    <BookOpenIcon className="size-4" />
                    <span>{statusDescription}</span>
                  </div>
                </ItemTitle>
                <ItemDescription className="text-xs md:text-sm">
                  <span className="grid gap-1 md:grid-cols-3">
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.docsPath}
                      </span>
                      <span className="ml-1 break-all text-muted-foreground">
                        {status.docs_path}
                      </span>
                    </span>
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.docCount}
                      </span>
                      <span className="ml-1 text-muted-foreground">
                        {status.doc_count}
                      </span>
                    </span>
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.collectionName}
                      </span>
                      <span className="ml-1 text-muted-foreground">
                        {status.collection_name}
                      </span>
                    </span>
                  </span>
                </ItemDescription>
              </ItemContent>
            </Item>
          )
        )}
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.actions.reindexTitle}
        description={t.settings.knowledge.actions.reindexDescription}
      >
        <Button
                  type="button"
                  variant="outline"
                  disabled={isKnowledgeMutating}
                  onClick={() => reindexMutation.mutate()}
                >
          <RefreshCwIcon className="mr-2 size-4" />
          {reindexMutation.isPending
            ? t.settings.knowledge.actions.reindexing
            : t.settings.knowledge.actions.reindex}
        </Button>
        {reindexMutation.error && (
          <p className="text-destructive mt-2 text-xs md:text-sm">
            {t.settings.knowledge.actions.reindexError}:{" "}
            {reindexMutation.error.message}
          </p>
        )}
        {reindexMutation.isSuccess && !reindexMutation.error && (
          <p className="text-muted-foreground mt-2 text-xs md:text-sm">
            {t.settings.knowledge.actions.reindexSuccess}
          </p>
        )}
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.upload.title}
        description={t.settings.knowledge.upload.description}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".md,.markdown,.pdf,.txt"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={isKnowledgeMutating}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isKnowledgeMutating}
                >
                  <UploadIcon className="mr-2 size-4" />
                  {t.settings.knowledge.upload.selectFile}
                </Button>
              </div>
              <div className="text-muted-foreground text-xs md:text-sm">
                {selectedFile ? (
                  <span>
                    {t.settings.knowledge.upload.selectedFile}: {selectedFile.name}
                    <span className="ml-2 text-muted-foreground">
                      ({formatBytes(selectedFile.size)})
                    </span>
                    {isLargeFile && (
                      <span className="ml-2 text-blue-500">
                        (分片上传)
                      </span>
                    )}
                  </span>
                ) : (
                  t.settings.knowledge.upload.noFile
                )}
              </div>
            </div>

            <div className="flex flex-col items-start gap-2 md:items-end">
              <div className="flex items-center gap-2">
                <Switch
                  checked={autoReindex}
                  onCheckedChange={setAutoReindex}
                  disabled={isKnowledgeMutating}
                />
                <span className="text-xs md:text-sm">
                  {t.settings.knowledge.upload.autoReindex}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {isUploading && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleCancelUpload}
                  >
                    <XIcon className="mr-2 size-4" />
                    取消
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  disabled={!selectedFile || isKnowledgeMutating}
                  onClick={() => void handleUpload()}
                >
                  {isUploading
                    ? t.settings.knowledge.upload.uploading
                    : t.settings.knowledge.upload.uploadButton}
                </Button>
              </div>
            </div>
          </div>

          {/* Upload Progress */}
          {isUploading && uploadProgress && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>上传进度</span>
                <span>
                  {formatBytes(uploadProgress.uploadedBytes)} / {formatBytes(uploadProgress.totalBytes)}
                  ({Math.round(uploadProgress.progress * 100)}%)
                </span>
              </div>
              <Progress value={uploadProgress.progress * 100} className="h-2" />
            </div>
          )}

          {/* Error message */}
          {uploadError && (
            <p className="text-destructive text-xs md:text-sm">
              {t.settings.knowledge.upload.error}: {uploadError.message}
            </p>
          )}

          {/* Success message */}
          {uploadSuccess && !uploadError && (
            <p className="text-muted-foreground text-xs md:text-sm">
              {t.settings.knowledge.upload.success}
            </p>
          )}

          {hasActiveKnowledgeJobs && (
            <p className="text-muted-foreground text-xs md:text-sm">
              知识库正在解析或重建索引，暂时不能上传、删除或重新索引。
            </p>
          )}
        </div>
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.docs.title}
        description={t.settings.knowledge.docs.description}
      >
        {isDocsLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : docsError ? (
          <div>Error: {docsError.message}</div>
        ) : docs.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.knowledge.docs.empty}
          </div>
        ) : (
          <div className="border-border divide-border rounded-md border text-xs md:text-sm">
            <div className="bg-muted grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_80px] gap-2 border-b px-3 py-2 font-medium">
              <div>{t.settings.knowledge.docs.filename}</div>
              <div>{t.settings.knowledge.docs.size}</div>
              <div className="text-right">
                {t.settings.knowledge.docs.actions}
              </div>
            </div>
            <div className="divide-y">
              {docs.map((doc) => (
                <div
                  key={doc.filename}
                  className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_80px] items-center gap-2 px-3 py-2"
                >
                  <div className="truncate">{doc.filename}</div>
                  <div className="text-muted-foreground">
                    {(doc.size / 1024).toFixed(1)} KB
                  </div>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      disabled={isKnowledgeMutating}
                      onClick={() =>
                        deleteMutation.mutate(doc.filename)
                      }
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </SettingsSection>
    </div>
  );
}
