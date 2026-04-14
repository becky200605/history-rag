"use client";

import {
  BookmarkPlusIcon,
  BookOpenIcon,
  CheckSquareIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FileIcon,
  FolderIcon,
  Loader2Icon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  buildFileTags,
  canOpenManagedFile,
  canRetryManagedFile,
  formatCompactTime,
  getCoverTone,
  getFolderDisplayName,
  getManagedFileCoverImageUrl,
  knowledgeTypeLabel,
  statusLabel,
  statusVariant,
  type FolderTreeNode,
  type ManagedKnowledgeFile,
} from "./knowledge-management-page.utils";

export function FolderTreeBranch({
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
          "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition",
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

export function KnowledgeManagementHero({
  searchQuery,
  onSearchQueryChange,
  selectedFolderPath,
  systemFolderTree,
  onSelectFolder,
}: {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  selectedFolderPath: string;
  systemFolderTree: FolderTreeNode[];
  onSelectFolder: (path: string) => void;
}) {
  return (
    <section className="relative w-full shrink-0 overflow-hidden bg-white px-6 pb-2 pt-6">
      <div className="absolute inset-x-0 top-0 h-px bg-slate-100"></div>
      
      <div className="z-10 flex w-full min-w-0 flex-col">

        <div className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white/80 shadow-sm backdrop-blur-sm transition-all focus-within:shadow-md">
          <div className="relative h-12">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
              <Input
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="请输入书名、标签或文件名进行馆藏检索..."
                className="h-full border-none bg-transparent pl-11 text-sm shadow-none focus-visible:ring-0"
              />
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-slate-100 bg-[#fdfdfd] p-3 px-6 select-none overflow-x-auto">
            <CategoryCheckbox
              active={selectedFolderPath === "all"}
              label="全部属性"
              onClick={() => onSelectFolder("all")}
            />
            {systemFolderTree.map((folderNode) => (
              <CategoryCheckbox
                key={folderNode.path}
                active={
                  selectedFolderPath === folderNode.path ||
                  selectedFolderPath.startsWith(`${folderNode.path}/`)
                }
                label={folderNode.name}
                onClick={() => onSelectFolder(folderNode.path)}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function KnowledgeManagementSidebar({
  folderTree,
  selectedFolderPath,
  expandedFolderPaths,
  onSelectFolder,
  onToggleFolder,
  selectedFolderNode,
  onDeleteFolder,
}: {
  folderTree: FolderTreeNode[];
  selectedFolderPath: string;
  expandedFolderPaths: string[];
  onSelectFolder: (path: string) => void;
  onToggleFolder: (path: string) => void;
  selectedFolderNode: FolderTreeNode | null;
  onDeleteFolder: () => void;
}) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-slate-200 bg-white md:w-80 md:border-b-0 md:border-r">
      <div className="border-b border-slate-100 px-4 py-4">
        <button
          type="button"
          onClick={() => onSelectFolder("all")}
          className={cn(
            "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition",
            selectedFolderPath === "all"
              ? "bg-[rgb(241,248,249)] text-[rgb(23,89,108)]"
              : "text-slate-700 hover:bg-slate-50",
          )}
        >
          <span className="font-medium">全部资料</span>
          <span className="text-xs text-slate-400">根目录</span>
        </button>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-4">
        {folderTree.map((node) => (
          <FolderTreeBranch
            key={node.path}
            node={node}
            selectedPath={selectedFolderPath}
            expandedPaths={expandedFolderPaths}
            onSelect={onSelectFolder}
            onToggle={onToggleFolder}
          />
        ))}
      </div>

      {selectedFolderNode ? (
        <div className="border-t border-slate-100 px-4 py-4">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-sm font-medium text-slate-900">
              {getFolderDisplayName(selectedFolderNode.name)}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              当前目录共 {selectedFolderNode.fileCount} 份资料
            </div>
            {selectedFolderNode.deletable ? (
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full rounded-md border-red-200 text-red-700 hover:bg-red-50"
                onClick={onDeleteFolder}
              >
                <Trash2Icon className="mr-1.5 size-4" />
                删除当前个人文件夹
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

export function KnowledgeManagementToolbar({
  breadcrumbs,
  onSelectFolder,
  onOpenUpload,
  onOpenCreateFolder,
  onRefresh,
  isRefreshing,
  onStartChat,
  selectedCount,
  onToggleAllVisible,
  allVisibleSelected,
}: {
  breadcrumbs: Array<{ name: string; path: string }>;
  onSelectFolder: (path: string) => void;
  onOpenUpload: () => void;
  onOpenCreateFolder: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  onStartChat: () => void;
  selectedCount: number;
  onToggleAllVisible: () => void;
  allVisibleSelected: boolean;
}) {
  return (
    <div className="sticky top-0 z-20 flex flex-col gap-3 border-b border-slate-100 bg-white px-6 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <button
          type="button"
          className="font-bold text-[#398298] transition hover:opacity-80"
          onClick={() => onSelectFolder("all")}
        >
          全部馆藏
        </button>
        {breadcrumbs.map((breadcrumb) => (
          <div key={breadcrumb.path} className="flex items-center gap-2">
            <ChevronRightIcon className="size-4 text-slate-300" />
            <button
              type="button"
              className="text-slate-700 transition hover:text-[rgb(57,130,152)]"
              onClick={() => onSelectFolder(breadcrumb.path)}
            >
              {getFolderDisplayName(breadcrumb.name)}
            </button>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 rounded-md border-[#398298]/30 px-3 text-xs text-[#23596c] hover:bg-[#398298]/10"
          onClick={onOpenUpload}
        >
          <PlusIcon className="mr-1.5 size-3.5" />
          上传档案
        </Button>
        <Button 
          type="button" 
          variant="outline" 
          size="sm" 
          className="h-8 rounded-md border-[#398298]/30 px-3 text-xs text-[#23596c] hover:bg-[#398298]/10"
          onClick={onOpenCreateFolder}
        >
          <FolderIcon className="mr-1.5 size-3.5" />
          新建文件夹
        </Button>
        <Button 
          type="button" 
          variant="outline" 
          size="icon" 
          className="h-8 w-8 shrink-0 rounded-md border-[#398298]/30 text-[#23596c] hover:bg-[#398298]/10"
          onClick={onRefresh} 
          disabled={isRefreshing}
        >
          <RefreshCwIcon className={cn("size-3.5", isRefreshing && "animate-spin")} />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 rounded-md border-[#398298]/30 px-3 text-xs text-[#23596c] hover:bg-[#398298]/10"
          onClick={onStartChat}
          disabled={selectedCount === 0}
        >
          <BookmarkPlusIcon className="mr-1.5 size-3.5" />
          选中提问 ({selectedCount})
        </Button>
        <button
          type="button"
          className="flex h-8 items-center gap-1.5 px-2 text-xs font-medium text-slate-500 transition hover:text-[#398298]"
          onClick={onToggleAllVisible}
        >
          {allVisibleSelected ? (
            <CheckSquareIcon className="size-3.5 text-[#398298]" />
          ) : (
            <SquareIcon className="size-3.5" />
          )}
          全选文档
        </button>
      </div>
    </div>
  );
}

export function KnowledgeFolderGrid({
  folders,
  onSelectFolder,
  onOpenFolderMenu,
}: {
  folders: FolderTreeNode[];
  onSelectFolder: (path: string) => void;
  onOpenFolderMenu: (folder: FolderTreeNode, event: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  if (folders.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-x-12 gap-y-2 px-6 py-2 select-none">
      {folders.map((folder) => (
        <button
          key={folder.path}
          type="button"
          onClick={() => onSelectFolder(folder.path)}
          onContextMenu={(event) => onOpenFolderMenu(folder, event)}
          className="group flex flex-row items-center gap-2 transition hover:opacity-80 active:scale-95"
        >
          <div className="flex size-8 shrink-0 items-center justify-center text-[rgb(57,130,152)] group-hover:text-[#398298]">
            <FolderIcon className="size-4.5 stroke-[1.5]" />
          </div>
          <div className="flex flex-row items-baseline gap-2">
            <span className="text-sm font-semibold text-slate-700 group-hover:text-[rgb(57,130,152)]">
              {getFolderDisplayName(folder.name)}
            </span>
            <span className="text-[10px] font-medium text-slate-400">
              ({folder.fileCount})
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

export function KnowledgeFileCard({
  file,
  isSelected,
  onToggleSelection,
  onOpenMetadata,
  onMoveFile,
  onRetry,
  onDelete,
  readerHref,
  personalSpacesCount,
  isDeleting,
  isRetrying,
}: {
  file: ManagedKnowledgeFile;
  isSelected: boolean;
  onToggleSelection: () => void;
  onOpenMetadata: () => void;
  onMoveFile: () => void;
  onRetry: () => void;
  onDelete: () => void;
  readerHref: string | null;
  personalSpacesCount: number;
  isDeleting: boolean;
  isRetrying: boolean;
}) {
  const tags = buildFileTags(file);
  const coverTone = getCoverTone(file.title);
  const canOpenReader = canOpenManagedFile(file, readerHref);
  const canRetry = canRetryManagedFile(file);
  const coverImageUrl = useMemo(() => getManagedFileCoverImageUrl(file), [file]);
  const [coverImageFailed, setCoverImageFailed] = useState(false);
  const showCoverImage = Boolean(coverImageUrl) && !coverImageFailed;

  return (
    <article
      className={cn(
        "group relative flex overflow-hidden rounded-lg border bg-white shadow-sm transition hover:shadow-md",
        isSelected ? "border-[rgb(57,130,152)] ring-1 ring-[rgb(57,130,152)]/15" : "border-slate-200",
      )}
    >
      <div className="flex w-full flex-col lg:flex-row">
        {/* Pseudo-Book Cover Area */}
        <div
          className={cn(
            "relative flex w-full shrink-0 cursor-pointer flex-col items-center justify-center p-3 lg:w-[132px]",
            coverTone,
          )}
          onClick={onToggleSelection}
        >
           {/* Minimal spine effect */}
           <div className="absolute inset-y-0 left-0 w-1 bg-white/20" />
           
           <button
             type="button"
             className={cn(
               "absolute left-2 top-2 z-20 flex size-5 items-center justify-center rounded-sm bg-white shadow-sm transition",
               isSelected ? "text-[rgb(57,130,152)]" : "text-slate-400 hover:text-[rgb(57,130,152)]",
             )}
             onClick={(event) => {
               event.stopPropagation();
               onToggleSelection();
             }}
           >
             {isSelected ? <CheckSquareIcon className="size-3.5" /> : <SquareIcon className="size-3.5" />}
           </button>

           {showCoverImage && coverImageUrl ? (
             <div className="relative mb-0 h-[96px] w-[68px] overflow-hidden rounded-sm border border-white/10 bg-white/10 shadow-lg">
               <img
                 src={coverImageUrl}
                 alt={`${file.title} 封面预览`}
                 className="h-full w-full object-cover"
                 onError={() => setCoverImageFailed(true)}
               />
             </div>
           ) : (
             <div className="relative mb-0 flex size-12 items-center justify-center rounded-sm bg-white/5 text-2xl font-light text-white/50">
               {file.title?.charAt(0) ?? "?"}
             </div>
           )}
           
           <div className="mt-1 text-center">
             <div className="line-clamp-1 px-2 text-[9px] font-bold uppercase tracking-tighter text-white/60">
                {file.extension?.replace(".", "") ?? "DOC"}
             </div>
           </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col p-4 pr-5">
           <div className="relative flex min-w-0 flex-col gap-2.5">
              {/* Actions shifted to Top Right */}
              <div className="absolute right-0 top-0 flex items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                {file.source === "global" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7 rounded-md text-slate-400 hover:bg-slate-100 hover:text-[rgb(57,130,152)]"
                    onClick={onOpenMetadata}
                  >
                    <PencilIcon className="size-3.5" />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7 rounded-md text-slate-400 hover:bg-slate-100 hover:text-[rgb(57,130,152)]"
                    onClick={onMoveFile}
                    disabled={personalSpacesCount <= 1}
                  >
                    <FolderIcon className="size-3.5" />
                  </Button>
                )}

                {canRetry ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7 rounded-md text-slate-400 hover:bg-slate-100 hover:text-[rgb(57,130,152)]"
                    onClick={onRetry}
                    disabled={isRetrying}
                  >
                    {isRetrying ? <Loader2Icon className="size-3.5 animate-spin" /> : <RefreshCwIcon className="size-3.5" />}
                  </Button>
                ) : null}

                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-7 rounded-md text-slate-400 hover:bg-red-50 hover:text-red-600"
                  onClick={onDelete}
                  disabled={isDeleting}
                >
                  {isDeleting ? <Loader2Icon className="size-3.5 animate-spin" /> : <Trash2Icon className="size-3.5" />}
                </Button>

                {readerHref && (
                  <a
                    href={readerHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex size-7 items-center justify-center rounded-md bg-slate-50 text-slate-400 transition hover:bg-[rgb(57,130,152)] hover:text-white"
                  >
                    <BookOpenIcon className="size-3.5" />
                  </a>
                ) }
              </div>

              <div className="min-w-0 space-y-1.5 pr-28"> {/* Room for buttons */}
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={statusVariant(file.parseStatus)} className="h-4 px-1.5 text-[9px] font-medium tracking-tight">{statusLabel(file.parseStatus)}</Badge>
                  <Badge variant="outline" className="h-4 px-1.5 text-[9px] font-medium tracking-tight">{knowledgeTypeLabel(file.type)}</Badge>
                </div>

                <div className="min-w-0">
                  {canOpenReader && readerHref ? (
                    <a
                      href={readerHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="line-clamp-1 text-base font-bold text-slate-900 leading-snug transition hover:text-[rgb(57,130,152)]"
                    >
                      {file.title}
                    </a>
                  ) : (
                    <div className="line-clamp-1 text-base font-bold text-slate-900 leading-snug">{file.title}</div>
                  )}
                  <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500/80">
                    <span className="font-medium text-slate-600">摘要：</span>
                    {file.summary?.trim() ?? "无"}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] text-slate-400">
                 <div className="flex items-center gap-1.5">
                   <span className="shrink-0">来源:</span>
                   <span className="font-medium text-slate-600">{file.source === "global" ? "系统" : "个人"}</span>
                 </div>
                 <div className="flex items-center gap-1.5">
                   <span className="shrink-0">收录于:</span>
                   <span className="font-medium text-slate-600">{formatCompactTime(file.modified)}</span>
                 </div>
                 <div className="flex items-center gap-1.5">
                   <span className="shrink-0">目录:</span>
                   <span className="font-semibold text-[#398298]">{file.folderDisplay}</span>
                 </div>
              </div>

              {tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tags.slice(0, 10).map((tag) => (
                    <Badge key={tag} variant="secondary" className="bg-slate-50/50 text-[9px] text-slate-400 border-none px-1 h-3.5">
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}
           </div>
        </div>
      </div>
    </article>
  );
}

export function KnowledgeLoadingState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-slate-200 bg-white py-16 text-slate-500 shadow-sm">
      <Loader2Icon className="mb-4 size-8 animate-spin text-[rgb(57,130,152)]" />
      正在检索文献馆藏...
    </div>
  );
}

export function KnowledgeErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
      {message}
    </div>
  );
}

export function KnowledgeEmptyState({
  hasCurrentLevelEntries,
}: {
  hasCurrentLevelEntries: boolean;
}) {
  if (hasCurrentLevelEntries) {
    return null;
  }

  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-16 text-slate-400">
      <FileIcon className="mb-4 size-14 text-slate-200" />
      <p className="text-base font-medium text-slate-500">此分类下暂无相关文献文档。</p>
      <p className="mt-1 text-xs">可以尝试放宽检索条件，或切换到其他目录查看。</p>
    </div>
  );
}

function CategoryCheckbox({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 transition select-none group focus:outline-none",
        active ? "text-[rgb(57,130,152)]" : "text-slate-500 hover:text-slate-700",
      )}
    >
      <div className={cn(
        "flex size-4 items-center justify-center rounded-sm border transition",
        active 
          ? "border-[rgb(57,130,152)] bg-[rgb(57,130,152)] text-white shadow-sm" 
          : "border-slate-300 bg-white group-hover:border-[rgb(57,130,152)]"
      )}>
        {active && <CheckSquareIcon className="size-3 stroke-[3]" />}
      </div>
      <span className="text-sm font-medium">{label}</span>
    </button>
  );
}
