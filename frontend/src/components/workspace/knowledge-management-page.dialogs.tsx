"use client";

import { ArrowRightIcon, Loader2Icon, PlusIcon, UploadIcon } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";

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
import { Textarea } from "@/components/ui/textarea";

import {
  documentTypeOptions,
  getFolderDisplayName,
  knowledgeTypeOptions,
  languageOptions,
  layoutOptions,
  type DocumentTypeHint,
  type LanguageHint,
  type LayoutHint,
  type MetadataFormState,
  type UploadFormState,
} from "./knowledge-management-page.utils";

export function UploadDialog({
  open,
  onOpenChange,
  form,
  setForm,
  targetMode,
  targetFolderLabel,
  onPickFiles,
  onCancel,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: UploadFormState;
  setForm: Dispatch<SetStateAction<UploadFormState>>;
  targetMode: "global" | "personal";
  targetFolderLabel: string;
  onPickFiles: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">
            上传到{targetFolderLabel}
          </DialogTitle>
          <DialogDescription className="text-slate-600">
            {targetMode === "global"
              ? "文件会进入当前系统文件夹。"
              : "文件会进入当前个人文件夹。"}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="rounded-xl border border-accent/10 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-900">选择文件</div>
                <div className="text-xs text-slate-500">
                  PDF、Markdown、Office 文档都可以批量上传。
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="border-primary/20 bg-white text-primary hover:bg-primary/5"
                onClick={onPickFiles}
                disabled={isPending}
              >
                选择文件
              </Button>
            </div>

            <div className="mt-3 rounded-lg border border-dashed border-accent/20 bg-stone-50/50 p-3">
              {form.files.length === 0 ? (
                <div className="text-sm text-slate-500">还没有选择文件。</div>
              ) : (
                <div className="space-y-1">
                  <div className="text-sm font-medium text-slate-900">
                    已选择 {form.files.length} 个文件
                  </div>
                  <div className="max-h-28 space-y-1 overflow-auto text-xs text-slate-600">
                    {form.files.map((file) => (
                      <div key={`${file.name}-${file.size}`}>{file.name}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-3 rounded-xl border border-accent/10 bg-white p-4 md:grid-cols-3">
            <SelectField
              label="文档类型"
              value={form.documentTypeHint}
              options={documentTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  documentTypeHint: value as DocumentTypeHint,
                }))
              }
            />
            <SelectField
              label="语言线索"
              value={form.languageHint}
              options={languageOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  languageHint: value as LanguageHint,
                }))
              }
            />
            <SelectField
              label="版式线索"
              value={form.layoutHint}
              options={layoutOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  layoutHint: value as LayoutHint,
                }))
              }
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending || form.files.length === 0}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <UploadIcon className="size-4" />}
            开始上传
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CreateFolderDialog({
  open,
  onOpenChange,
  title,
  description,
  value,
  onValueChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">{title}</DialogTitle>
          <DialogDescription className="text-slate-600">{description}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <label className="text-sm font-medium text-slate-800">文件夹名称</label>
          <Input
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            placeholder="例如：晚清财政"
            className="bg-white"
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <PlusIcon className="size-4" />}
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MoveFileDialog({
  open,
  onOpenChange,
  folders,
  value,
  onValueChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: string[];
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">移动文件</DialogTitle>
          <DialogDescription className="text-slate-600">
            将个人文件移动到另一个个人文件夹。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <label className="text-sm font-medium text-slate-800">目标文件夹</label>
          <Select value={value} onValueChange={onValueChange}>
            <SelectTrigger className="bg-white text-sm">
              <SelectValue placeholder="选择文件夹" />
            </SelectTrigger>
            <SelectContent>
              {folders.map((folder) => (
                <SelectItem key={folder} value={folder}>
                  {getFolderDisplayName(folder)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending || !value}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <ArrowRightIcon className="size-4" />}
            移动
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MetadataDialog({
  open,
  onOpenChange,
  form,
  setForm,
  errorMessage,
  isSaving,
  isRegenerating,
  onRegenerate,
  onCancel,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: MetadataFormState;
  setForm: Dispatch<SetStateAction<MetadataFormState>>;
  errorMessage?: string | null;
  isSaving: boolean;
  isRegenerating: boolean;
  onRegenerate: () => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">修改书籍标签</DialogTitle>
          <DialogDescription className="text-slate-600">
            修改的是书级 metadata，会影响书目路由和候选排序，但不会重跑 OCR 或向量化。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-3 md:grid-cols-2">
            <SelectField
              label="检索类型"
              value={form.type}
              options={knowledgeTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  type: value as MetadataFormState["type"],
                }))
              }
            />

            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">文件夹路径</label>
              <Input
                value={form.folder}
                onChange={(event) =>
                  setForm((current) => ({ ...current, folder: event.target.value }))
                }
                placeholder="例如：财政史/清代"
                className="bg-white"
              />
              <p className="text-xs text-slate-500">
                使用 `/` 表示多级目录；留空时会按首个标签回退归档。
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <SelectField
              label="语言线索"
              value={form.languageHint}
              options={languageOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  languageHint: value as LanguageHint,
                }))
              }
            />
            <SelectField
              label="版式线索"
              value={form.layoutHint}
              options={layoutOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  layoutHint: value as LayoutHint,
                }))
              }
            />
          </div>

          <div className="grid gap-2">
            <SelectField
              label="文档类型线索"
              value={form.documentTypeHint}
              options={documentTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  documentTypeHint: value as DocumentTypeHint,
                }))
              }
            />
            <p className="text-xs text-slate-500">
              修改线索后不会自动重跑 OCR；保存后可直接点击“重新入库”验证召回效果。
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <TextField
              label="分类"
              value={form.categories}
              placeholder="通史, 财政史, 制度史"
              onChange={(value) => setForm((current) => ({ ...current, categories: value }))}
            />
            <TextField
              label="时代"
              value={form.eras}
              placeholder="先秦, 唐宋, 明清"
              onChange={(value) => setForm((current) => ({ ...current, eras: value }))}
            />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <TextField
              label="地域"
              value={form.regions}
              placeholder="全国, 江南, 四川"
              onChange={(value) => setForm((current) => ({ ...current, regions: value }))}
            />
            <TextField
              label="关键词"
              value={form.keywords}
              placeholder="赋税, 盐政, 漕运"
              onChange={(value) => setForm((current) => ({ ...current, keywords: value }))}
            />
          </div>

          <div className="grid gap-2">
            <label className="text-sm font-medium text-slate-800">摘要</label>
            <Textarea
              value={form.summary}
              onChange={(event) =>
                setForm((current) => ({ ...current, summary: event.target.value }))
              }
              placeholder="补充这本书的覆盖范围或定位"
              rows={5}
              className="bg-white"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">作者</label>
              <Input
                value={form.author}
                onChange={(event) =>
                  setForm((current) => ({ ...current, author: event.target.value }))
                }
                placeholder="张之洞"
                className="bg-white"
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">出版社</label>
              <Input
                value={form.publisher}
                onChange={(event) =>
                  setForm((current) => ({ ...current, publisher: event.target.value }))
                }
                placeholder="商务印书馆"
                className="bg-white"
              />
            </div>
          </div>

          {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onRegenerate}
            disabled={isSaving || isRegenerating}
          >
            {isRegenerating ? <Loader2Icon className="size-4 animate-spin" /> : null}
            AI 生成
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isSaving || isRegenerating}
          >
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSave}
            disabled={isSaving || isRegenerating}
          >
            {isSaving ? <Loader2Icon className="size-4 animate-spin" /> : null}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SelectField({
  label,
  value,
  options,
  onValueChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-slate-800">{label}</label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="bg-white text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function TextField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-slate-800">{label}</label>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="bg-white"
      />
    </div>
  );
}
