"use client";

import type { AIMessage } from "@langchain/langgraph-sdk";
import {
  CheckCircle2Icon,
  CircleDotIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useI18n } from "@/core/i18n/hooks";
import { extractTextFromMessage, hasToolCalls } from "@/core/messages/utils";
import { useSubtask } from "@/core/tasks/context";
import type { Todo } from "@/core/todos";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

function statusLabel(
  status: Todo["status"] | "in_progress" | "completed" | "failed" | undefined,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (!status || status === "pending") {
    return "Pending";
  }
  return t.subtasks[status];
}

function latestProgressText(message: AIMessage | undefined, detail: string | null) {
  if (!message) {
    return detail;
  }
  const text = extractTextFromMessage(message).trim();
  if (text) {
    return text;
  }
  return detail;
}

export function SubtaskDetailSheet({
  open,
  todo,
  onOpenChange,
}: {
  open: boolean;
  todo: Todo | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const linkedSubtask = useSubtask(todo?.task_id ?? "");

  const detailStatus = linkedSubtask?.status ?? todo?.status;
  const liveAction =
    linkedSubtask?.status === "in_progress" &&
    linkedSubtask.latestMessage &&
    hasToolCalls(linkedSubtask.latestMessage)
      ? explainLastToolCall(linkedSubtask.latestMessage, t)
      : null;
  const latestProgress = latestProgressText(linkedSubtask?.latestMessage, liveAction);

  const statusIcon = useMemo(() => {
    if (detailStatus === "completed") {
      return <CheckCircle2Icon className="size-4 text-emerald-600" />;
    }
    if (detailStatus === "failed") {
      return <XCircleIcon className="size-4 text-red-500" />;
    }
    if (detailStatus === "in_progress") {
      return <Loader2Icon className="size-4 animate-spin text-primary" />;
    }
    return <CircleDotIcon className="size-4 text-muted-foreground/70" />;
  }, [detailStatus]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b border-border/60 px-6 py-5">
          <SheetTitle className="pr-8 text-base leading-relaxed">
            {todo?.content ?? "子任务详情"}
          </SheetTitle>
          <SheetDescription className="flex items-center gap-2 text-xs">
            {statusIcon}
            <span>{statusLabel(detailStatus, t)}</span>
          </SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-5">
          {!todo ? (
            <div className="text-muted-foreground text-sm">未选中子任务。</div>
          ) : (
            <div className="space-y-5">
              {todo.task_id && (
                <Section title="任务标识">
                  <div className="text-[11px] uppercase tracking-widest text-muted-foreground/70">
                    {todo.subagent_type ?? linkedSubtask?.subagent_type ?? "subagent"} · {todo.task_id}
                  </div>
                </Section>
              )}

              {todo.task_prompt && (
                <Section title="任务说明">
                  <DetailBlock>{todo.task_prompt}</DetailBlock>
                </Section>
              )}

              {latestProgress && (
                <Section title="当前进度">
                  <DetailBlock emphasis={detailStatus === "in_progress"}>
                    {latestProgress}
                  </DetailBlock>
                </Section>
              )}

              {linkedSubtask?.result && (
                <Section title="执行结果">
                  <DetailBlock>{linkedSubtask.result}</DetailBlock>
                </Section>
              )}

              {!linkedSubtask?.result && todo.result_summary && (
                <Section title="结果摘要">
                  <DetailBlock>{todo.result_summary}</DetailBlock>
                </Section>
              )}

              {linkedSubtask?.error && (
                <Section title="错误信息">
                  <DetailBlock tone="danger">{linkedSubtask.error}</DetailBlock>
                </Section>
              )}

              {!linkedSubtask?.error && todo.error && (
                <Section title="错误信息">
                  <DetailBlock tone="danger">{todo.error}</DetailBlock>
                </Section>
              )}

              {!linkedSubtask && !todo.result_summary && !todo.error && !todo.task_prompt && (
                <div className="text-muted-foreground text-sm">
                  这个 todo 还没有关联到可展示的子任务详情。
                </div>
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-widest text-muted-foreground/70 uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

function DetailBlock({
  children,
  emphasis = false,
  tone = "default",
}: {
  children: React.ReactNode;
  emphasis?: boolean;
  tone?: "default" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border/50 bg-muted/20 px-4 py-3 text-sm leading-7 whitespace-pre-wrap break-words",
        emphasis ? "border-primary/40 bg-primary/5 text-foreground" : "text-muted-foreground/90",
        tone === "danger" ? "border-red-500/30 bg-red-500/5 text-red-600 dark:text-red-400" : "",
      )}
    >
      {children}
    </div>
  );
}
