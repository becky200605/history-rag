"use client";

import {
  ArrowUpRightIcon,
  BookOpenIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  EllipsisIcon,
  FileTextIcon,
  FolderIcon,
  LibraryBigIcon,
  Loader2Icon,
  PanelLeftIcon,
  PlusIcon,
  SearchIcon,
  Settings2Icon,
} from "lucide-react";
import { useState, type MouseEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  buildManagedFileOriginalHref,
  canOpenManagedFile,
  canReparseManagedFile,
  canRetryManagedFile,
  getManagedFileCoverImageUrl,
  statusLabel,
  type FolderTreeNode,
  type ManagedKnowledgeFile,
} from "./knowledge-management-page.utils";

type FolderNavigationProps = {
  selectedPath: string;
  expandedPaths: string[];
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  onContextMenu?: (folder: FolderTreeNode, event: MouseEvent<HTMLButtonElement>) => void;
};

function FolderTreeBranch({
  node,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
  onContextMenu,
  depth = 0,
}: FolderNavigationProps & { node: FolderTreeNode; depth?: number }) {
  const expanded = expandedPaths.includes(node.path);
  const selected = selectedPath === node.path;
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={cn(
          "flex min-h-10 items-center rounded-md",
          selected ? "bg-[#f0e3dc] text-[#74362d]" : "hover:bg-[#eee9de] text-[#50483e]",
        )}
        style={{ paddingLeft: Math.min(depth, 5) * 12 + 3 }}
      >
        {hasChildren ? (
          <button
            type="button"
            aria-label={`${expanded ? "收起" : "展开"}${node.name}`}
            aria-expanded={expanded}
            onClick={() => onToggle(node.path)}
            className="grid size-7 shrink-0 cursor-pointer place-items-center rounded text-stone-500 hover:bg-white/70"
          >
            {expanded ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />}
          </button>
        ) : (
          <span className="w-7 shrink-0" />
        )}
        <button
          type="button"
          title={node.name}
          aria-current={selected ? "location" : undefined}
          onClick={() => onSelect(node.path)}
          onContextMenu={node.deletable && onContextMenu ? (event) => onContextMenu(node, event) : undefined}
          className={cn(
            "flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 rounded pr-2 text-left text-sm",
            (selected || depth === 0) && "font-semibold",
          )}
        >
          <FolderIcon className="size-4 shrink-0 text-[#92794d]" />
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
          <span className="shrink-0 text-xs text-[#75685b] tabular-nums">{node.fileCount}</span>
        </button>
      </div>
      {expanded && hasChildren && (
        <ul className="my-0.5 space-y-0.5">
          {node.children.map((child) => (
            <FolderTreeBranch
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={onSelect}
              onToggle={onToggle}
              onContextMenu={onContextMenu}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function KnowledgeManagementSidebar({
  folders,
  count,
  ...navigation
}: FolderNavigationProps & { folders: FolderTreeNode[]; count: number }) {
  return (
    <nav aria-label="馆藏分类" className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">
      <button
        type="button"
        aria-current={navigation.selectedPath === "all" ? "location" : undefined}
        onClick={() => navigation.onSelect("all")}
        className={cn(
          "mb-4 flex min-h-10 w-full cursor-pointer items-center gap-3 rounded-md px-3 text-left text-sm",
          navigation.selectedPath === "all" ? "bg-[#f0e3dc] font-semibold text-[#74362d]" : "text-[#50483e] hover:bg-[#eee9de]",
        )}
      >
        <LibraryBigIcon className="size-4 shrink-0 text-[#92794d]" />
        <span className="flex-1">全部馆藏</span>
        <span className="text-xs text-[#75685b] tabular-nums">{count}</span>
      </button>
      <ul className="space-y-1 border-t border-[#e7dfd1] pt-3">
        {folders.map((node) => <FolderTreeBranch key={node.path} node={node} {...navigation} />)}
      </ul>
    </nav>
  );
}

export function KnowledgeManagementToolbar({
  searchQuery,
  onSearchChange,
  onOpenFolders,
  onOpenUpload,
  onOpenCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onOpenReorganize,
  onOpenBatchGenerateSummary,
  onRefresh,
  isRefreshing,
}: {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onOpenFolders: () => void;
  onOpenUpload: () => void;
  onOpenCreateFolder: () => void;
  onRenameFolder?: () => void;
  onDeleteFolder?: () => void;
  onOpenReorganize: () => void;
  onOpenBatchGenerateSummary?: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[#eee6da] bg-[#fffdfa] px-4 py-3 sm:flex-nowrap sm:gap-3 sm:px-7">
      <Button type="button" variant="ghost" size="sm" onClick={onOpenFolders} className="lg:hidden">
        <PanelLeftIcon /> 分类
      </Button>
      <div role="search" className="relative min-w-32 flex-1 sm:max-w-xl">
        <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[#82725f]" />
        <Input
          type="search"
          aria-label="搜索馆藏"
          placeholder="搜索书名、标签或摘要"
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          className="h-10 rounded-md border-[#e9e0d3] bg-[#faf7ef] pl-10 text-sm text-[#352c23] placeholder:text-[#7b6c5d]"
        />
      </div>
      <div className="flex flex-1 justify-end gap-2">
        <Button type="button" onClick={onOpenUpload} className="h-10 bg-[#793b32] hover:bg-[#673027]">
          <PlusIcon /> 上传资料
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="outline" className="h-10 border-[#e9e0d3] bg-white text-[#504337] hover:bg-[#f4ede2] hover:text-[#504337]">
              <Settings2Icon /> 管理 <ChevronDownIcon className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuItem onSelect={onOpenCreateFolder}>新建文件夹</DropdownMenuItem>
            {onRenameFolder && <DropdownMenuItem onSelect={onRenameFolder}>重命名当前文件夹</DropdownMenuItem>}
            {onDeleteFolder && <DropdownMenuItem onSelect={onDeleteFolder} variant="destructive">删除当前文件夹</DropdownMenuItem>}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onOpenReorganize}>AI 整理目录</DropdownMenuItem>
            {onOpenBatchGenerateSummary && <DropdownMenuItem onSelect={onOpenBatchGenerateSummary}>批量生成摘要</DropdownMenuItem>}
            <DropdownMenuItem onSelect={onRefresh} disabled={isRefreshing}>刷新馆藏</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export function KnowledgeCover({ file, className }: { file: ManagedKnowledgeFile; className?: string }) {
  const coverUrl = getManagedFileCoverImageUrl(file);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  return (
    <span className={cn("relative grid h-20 w-14 shrink-0 place-items-center overflow-hidden rounded-[3px] border border-[#e7d9c4] bg-[#eee4d4] text-[#8a6748]", className)}>
      {coverUrl && coverUrl !== failedUrl ? (
        <img src={coverUrl} alt="" loading="lazy" className="size-full object-cover" onError={() => setFailedUrl(coverUrl)} />
      ) : (
        <BookOpenIcon aria-hidden className="size-5 stroke-[1.4]" />
      )}
    </span>
  );
}

export function KnowledgeFileCard({
  file,
  isSelected,
  onToggleSelection,
  onOpenDetails,
  onOpenMetadata,
  onMoveFile,
  onRetry,
  onReparse,
  onDelete,
  readerHref,
  personalSpacesCount,
  isDeleting,
  isRetrying,
  isReparsing,
}: {
  file: ManagedKnowledgeFile;
  isSelected: boolean;
  onToggleSelection: () => void;
  onOpenDetails: (trigger: HTMLButtonElement) => void;
  onOpenMetadata: () => void;
  onMoveFile: () => void;
  onRetry: () => void;
  onReparse: () => void;
  onDelete: () => void;
  readerHref: string | null;
  personalSpacesCount: number;
  isDeleting: boolean;
  isRetrying: boolean;
  isReparsing: boolean;
}) {
  const summary = file.summary?.trim();
  const originalHref = buildManagedFileOriginalHref(file);
  const format = file.extension?.replace(/^\./, "").toUpperCase();
  const byline = [file.author, file.publisher, format].filter(Boolean).join(" · ");
  const topics = [...new Set(file.keywords?.length ? file.keywords : file.categories ?? [])].slice(0, 3);

  return (
    <article className={cn(
      "flex min-w-0 flex-col rounded-xl border bg-[#fffefa] shadow-[0_2px_8px_#4a2c1710] transition-shadow hover:shadow-[0_4px_16px_#4a2c1717]",
      isSelected ? "border-[#a46757]" : "border-[#e7ded1]",
    )}>
      <div className="flex min-w-0 items-start gap-3.5 px-4 pt-4 sm:px-5 sm:pt-5">
        <button type="button" aria-label={`查看《${file.title}》详情`} onClick={(event) => onOpenDetails(event.currentTarget)} className="shrink-0 cursor-pointer rounded">
          <KnowledgeCover file={file} />
        </button>
        <div className="min-w-0 flex-1 pt-0.5">
          <button
            type="button"
            onClick={(event) => onOpenDetails(event.currentTarget)}
            title={file.title}
            className="line-clamp-2 cursor-pointer rounded text-left font-serif text-lg leading-snug font-semibold text-[#30261e] hover:text-[#793b32]"
          >
            {file.title}
          </button>
          {byline && <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-[#756859]">{byline}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <input type="checkbox" checked={isSelected} onChange={onToggleSelection} aria-label={`选中《${file.title}》`} className="size-4 cursor-pointer accent-[#793b32]" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={`管理《${file.title}》`} className="size-7 text-stone-600 hover:bg-[#f5eddf] hover:text-[#793b32]">
                {isDeleting || isRetrying || isReparsing ? <Loader2Icon className="animate-spin" /> : <EllipsisIcon />}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {file.source === "global" ? (
                <DropdownMenuItem onSelect={onOpenMetadata}>编辑资料信息</DropdownMenuItem>
              ) : (
                <DropdownMenuItem disabled={personalSpacesCount <= 1} onSelect={onMoveFile}>移动文件</DropdownMenuItem>
              )}
              {readerHref && canOpenManagedFile(file, readerHref) && (
                <DropdownMenuItem asChild><a href={readerHref} target="_blank" rel="noopener noreferrer">结构化阅读</a></DropdownMenuItem>
              )}
              {canRetryManagedFile(file) && <DropdownMenuItem disabled={isRetrying} onSelect={onRetry}>重新入库</DropdownMenuItem>}
              {canReparseManagedFile(file) && <DropdownMenuItem disabled={isReparsing} onSelect={onReparse}>重新解析</DropdownMenuItem>}
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" disabled={isDeleting} onSelect={onDelete}>删除资料</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="flex-1 px-4 pt-4 pb-4 sm:px-5">
        {summary ? (
          <p className="line-clamp-4 text-[14px] leading-7 text-[#4f4438]">{summary}</p>
        ) : (
          <p className="text-sm leading-7 text-[#756859]">
            暂无摘要
            {file.parseStatus && <span className="ml-2 text-xs">· {statusLabel(file.parseStatus)}</span>}
          </p>
        )}
        {topics.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="主题">
            {topics.map((topic) => <li key={topic} className="max-w-full truncate rounded border border-[#eee4d5] bg-[#f8f2e6] px-2 py-0.5 text-xs text-[#6f5438]" title={topic}>{topic}</li>)}
          </ul>
        )}
      </div>
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 border-t border-[#eee6da] px-4 py-2 sm:px-5">
        <button type="button" onClick={(event) => onOpenDetails(event.currentTarget)} className="inline-flex cursor-pointer items-center gap-1 rounded text-sm font-medium text-[#793b32] hover:underline">
          查看详情 <ChevronRightIcon className="size-3.5" />
        </button>
        {originalHref ? (
          <a href={originalHref} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded text-sm text-[#594b3e] hover:text-[#793b32] hover:underline">
            阅读原文 <ArrowUpRightIcon className="size-3.5" />
          </a>
        ) : <span className="text-xs text-[#756859]">暂无原文</span>}
      </div>
    </article>
  );
}

export function KnowledgeEmptyState({ onClear }: { onClear?: () => void }) {
  return (
    <div className="grid justify-items-center gap-3 rounded-xl border border-dashed border-[#e1d5c3] bg-[#fffefa] px-6 py-12 text-center">
      <FileTextIcon className="size-7 text-[#a18761]" />
      <p className="text-sm font-medium text-[#5d4e40]">{onClear ? "没有符合条件的资料" : "当前分类暂无资料"}</p>
      {onClear && <Button type="button" variant="link" size="sm" onClick={onClear}>清除搜索和筛选</Button>}
    </div>
  );
}
