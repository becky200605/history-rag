import {
  CheckCircle2Icon,
  ChevronRightIcon,
  ChevronUpIcon,
  CircleDotIcon,
  ListTodoIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { hasToolCalls } from "@/core/messages/utils";
import { useSubtask } from "@/core/tasks/context";
import type { Todo } from "@/core/todos";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import {
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
  QueueList,
} from "../ai-elements/queue";

export function TodoList({
  className,
  todos,
  collapsed = false,
  hidden = false,
  onToggle,
}: {
  className?: string;
  todos: Todo[];
  collapsed?: boolean;
  hidden?: boolean;
  onToggle?: () => void;
}) {
  const [expandedTodoIds, setExpandedTodoIds] = useState<Record<string, boolean>>({});
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const runningCount = todos.filter((t) => t.status === "in_progress").length;
  const failedCount = todos.filter((t) => t.status === "failed").length;
  return (
    <div
      className={cn(
        "flex h-fit w-full flex-col overflow-hidden rounded-t-2xl border border-border/50 bg-background/80 shadow-2xl backdrop-blur-xl transition-all duration-300 ease-in-out",
        hidden ? "pointer-events-none translate-y-12 opacity-0" : "translate-y-0 opacity-100",
        className,
      )}
    >
      <header
        className={cn(
          "flex min-h-10 shrink-0 cursor-pointer items-center justify-between px-5 text-sm transition-colors hover:bg-muted/30",
          collapsed ? "border-b-0" : "border-b border-border/40 bg-muted/20"
        )}
        onClick={() => {
          onToggle?.();
        }}
      >
        <div className="flex items-center gap-2.5 font-medium text-foreground/80">
          <ListTodoIcon className="size-4.5 text-accent" />
          <div className="tracking-tight">To-dos</div>
        </div>
        <div className="flex items-center gap-3">
          {(runningCount > 0 || failedCount > 0) && (
            <div className="text-[10px] font-semibold tracking-widest text-muted-foreground/70 uppercase">
              {runningCount > 0 ? `${runningCount} RUN` : ""}
              {runningCount > 0 && failedCount > 0 ? " · " : ""}
              {failedCount > 0 ? `${failedCount} FAIL` : ""}
            </div>
          )}
          <div className="text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
            {completedCount}/{todos.length}
          </div>
          <ChevronUpIcon
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-300",
              collapsed ? "" : "rotate-180",
            )}
          />
        </div>
      </header>
      <main
        className={cn(
          "flex grow flex-col overflow-hidden transition-all duration-300 ease-in-out",
          collapsed ? "h-0 opacity-0" : "h-auto max-h-64 opacity-100 py-3",
        )}
      >
        <QueueList className="w-full px-2">
          {todos.map((todo, i) => (
            <TodoListItem
              key={i + (todo.content ?? "")}
              todo={todo}
              expanded={Boolean(expandedTodoIds[todo.id ?? todo.task_id ?? String(i)])}
              onToggle={() => {
                const todoKey = todo.id ?? todo.task_id ?? String(i);
                setExpandedTodoIds((prev) => ({
                  ...prev,
                  [todoKey]: !prev[todoKey],
                }));
              }}
            />
          ))}
        </QueueList>
      </main>
    </div>
  );
}

function TodoListItem({
  todo,
  expanded,
  onToggle,
}: {
  todo: Todo;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const linkedSubtask = useSubtask(todo.task_id ?? "");
  const detailStatus = linkedSubtask?.status ?? todo.status;
  const detailLabel = useMemo(() => {
    if (!detailStatus) {
      return null;
    }
    if (detailStatus === "pending") {
      return "Pending";
    }
    return t.subtasks[detailStatus];
  }, [detailStatus, t]);

  const liveAction =
    linkedSubtask?.status === "in_progress" &&
    linkedSubtask.latestMessage &&
    hasToolCalls(linkedSubtask.latestMessage)
      ? explainLastToolCall(linkedSubtask.latestMessage, t)
      : null;

  const statusIcon =
    detailStatus === "completed" ? (
      <CheckCircle2Icon className="size-3.5 text-emerald-600" />
    ) : detailStatus === "failed" ? (
      <XCircleIcon className="size-3.5 text-red-500" />
    ) : detailStatus === "in_progress" ? (
      <Loader2Icon className="size-3.5 animate-spin text-primary" />
    ) : (
      <CircleDotIcon className="size-3.5 text-muted-foreground/70" />
    );

  const hasDetails = Boolean(
    todo.task_id ??
      linkedSubtask ??
      todo.result_summary ??
      todo.error ??
      todo.task_prompt,
  );

  return (
    <QueueItem className="py-1.5 transition-all hover:translate-x-0.5">
      <div className="flex items-start gap-3">
        <QueueItemIndicator
          className={cn(
            "mt-1.5",
            todo.status === "in_progress"
              ? "border-primary bg-primary shadow-[0_0_8px_rgba(126,51,46,0.4)]"
              : "",
            todo.status === "failed"
              ? "border-red-500 bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.35)]"
              : "",
          )}
          completed={todo.status === "completed"}
        />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={hasDetails ? onToggle : undefined}
            className={cn(
              "flex w-full items-start gap-2 text-left",
              hasDetails ? "cursor-pointer" : "cursor-default",
            )}
          >
            <div className="min-w-0 flex-1">
              <QueueItemContent
                className={cn(
                  "font-serif text-[14px] leading-relaxed",
                  todo.status === "in_progress"
                    ? "font-medium text-foreground"
                    : "text-muted-foreground/90",
                  todo.status === "completed"
                    ? "text-muted-foreground/50 italic"
                    : "",
                  todo.status === "failed"
                    ? "text-red-600 dark:text-red-400"
                    : "",
                )}
                completed={todo.status === "completed"}
              >
                {todo.content}
              </QueueItemContent>
              {(detailLabel ?? liveAction) && (
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground/75">
                  {statusIcon}
                  <span className="truncate">{liveAction ?? detailLabel}</span>
                </div>
              )}
            </div>
            {hasDetails && (
              <ChevronRightIcon
                className={cn(
                  "mt-0.5 size-4 shrink-0 text-muted-foreground/60 transition-transform",
                  expanded ? "rotate-90" : "",
                )}
              />
            )}
          </button>

          {hasDetails && expanded && (
            <div className="mt-2 space-y-2 rounded-xl border border-border/50 bg-muted/20 p-3">
              {todo.task_id && (
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60">
                  {todo.subagent_type ?? linkedSubtask?.subagent_type ?? "subagent"} · {todo.task_id}
                </div>
              )}
              {todo.task_prompt && (
                <div className="text-[12px] leading-relaxed text-muted-foreground/85">
                  {todo.task_prompt}
                </div>
              )}
              {liveAction && (
                <div className="text-[12px] leading-relaxed text-foreground/80">
                  当前动作：{liveAction}
                </div>
              )}
              {linkedSubtask?.result && (
                <div className="text-[12px] leading-relaxed text-muted-foreground/85">
                  {linkedSubtask.result}
                </div>
              )}
              {!linkedSubtask?.result && todo.result_summary && (
                <div className="text-[12px] leading-relaxed text-muted-foreground/85">
                  {todo.result_summary}
                </div>
              )}
              {linkedSubtask?.error && (
                <div className="text-[12px] leading-relaxed text-red-600 dark:text-red-400">
                  {linkedSubtask.error}
                </div>
              )}
              {!linkedSubtask?.error && todo.error && (
                <div className="text-[12px] leading-relaxed text-red-600 dark:text-red-400">
                  {todo.error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </QueueItem>
  );
}
