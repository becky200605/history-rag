import { ChevronUpIcon, ListTodoIcon } from "lucide-react";

import type { Todo } from "@/core/todos";
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
          <div className="text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
            {todos.filter(t => t.status === "completed").length}/{todos.length}
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
            <QueueItem 
              key={i + (todo.content ?? "")}
              className="py-1.5 transition-all hover:translate-x-0.5"
            >
              <div className="flex items-start gap-3">
                <QueueItemIndicator
                  className={cn(
                    "mt-1.5",
                    todo.status === "in_progress" ? "bg-primary shadow-[0_0_8px_rgba(126,51,46,0.4)] border-primary" : ""
                  )}
                  completed={todo.status === "completed"}
                />
                <QueueItemContent
                  className={cn(
                    "font-serif text-[14px] leading-relaxed",
                    todo.status === "in_progress" ? "font-medium text-foreground" : "text-muted-foreground/90",
                    todo.status === "completed" ? "text-muted-foreground/50 italic" : ""
                  )}
                  completed={todo.status === "completed"}
                >
                  {todo.content}
                </QueueItemContent>
              </div>
            </QueueItem>
          ))}
        </QueueList>
      </main>
    </div>
  );
}
