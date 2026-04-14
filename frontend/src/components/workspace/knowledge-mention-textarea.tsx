"use client";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { InputGroupTextarea } from "@/components/ui/input-group";
import {
  usePromptInputAttachments,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import type { MentionableKnowledgeMaterial } from "@/core/knowledge/mentions";
import type { SelectedMaterial } from "@/core/knowledge/selection";
import { cn } from "@/lib/utils";
import { BookOpenTextIcon, FolderIcon, LibraryBigIcon } from "lucide-react";
import {
  type ChangeEvent,
  type ClipboardEventHandler,
  type KeyboardEventHandler,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type ActiveMention = {
  start: number;
  end: number;
  query: string;
};

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}

function getActiveMention(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): ActiveMention | null {
  if (selectionStart !== selectionEnd) {
    return null;
  }

  let start = selectionStart;
  while (start > 0 && !/\s/.test(value[start - 1] ?? "")) {
    start -= 1;
  }

  const token = value.slice(start, selectionStart);
  if (
    !token.startsWith("@") ||
    token.startsWith("@《") ||
    token.includes("》")
  ) {
    return null;
  }

  return {
    start,
    end: selectionStart,
    query: token.slice(1),
  };
}

export function KnowledgeMentionTextarea({
  autoFocus,
  className,
  disabled,
  mentionables,
  placeholder,
  selectedMaterials = [],
}: {
  autoFocus?: boolean;
  className?: string;
  disabled?: boolean;
  mentionables: MentionableKnowledgeMaterial[];
  placeholder: string;
  selectedMaterials?: SelectedMaterial[];
}) {
  const { textInput } = usePromptInputController();
  const attachments = usePromptInputAttachments();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [isComposing, setIsComposing] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [activeIndex, setActiveIndex] = useState(0);

  const activeMention = useMemo(
    () =>
      isFocused
        ? getActiveMention(textInput.value, selection.start, selection.end)
        : null,
    [isFocused, selection.end, selection.start, textInput.value],
  );

  const filteredMentionables = useMemo(() => {
    if (!activeMention) {
      return [];
    }

    const query = normalizeSearchText(activeMention.query);
    const candidates = !query
      ? mentionables
      : mentionables.filter(
          (item) =>
            item.searchText.includes(query) ||
            normalizeSearchText(item.tokenLabel).includes(query),
        );

    return candidates.slice(0, 12);
  }, [activeMention, mentionables]);

  useEffect(() => {
    setActiveIndex(0);
  }, [activeMention?.query]);

  const syncSelection = (target: HTMLTextAreaElement) => {
    setSelection({
      start: target.selectionStart ?? 0,
      end: target.selectionEnd ?? 0,
    });
  };

  const focusTo = (cursor: number) => {
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(cursor, cursor);
      setSelection({ start: cursor, end: cursor });
    });
  };

  const selectMention = (material: MentionableKnowledgeMaterial) => {
    if (!activeMention) {
      return;
    }

    const nextValue =
      textInput.value.slice(0, activeMention.start) +
      `@《${material.tokenLabel}》 ` +
      textInput.value.slice(activeMention.end);
    const nextCursor = activeMention.start + material.tokenLabel.length + 4;

    textInput.setInput(nextValue);
    focusTo(nextCursor);
  };

  const handleKeyDown: KeyboardEventHandler<HTMLTextAreaElement> = (event) => {
    if (activeMention && filteredMentionables.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((current) =>
          current + 1 >= filteredMentionables.length ? 0 : current + 1,
        );
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) =>
          current - 1 < 0 ? filteredMentionables.length - 1 : current - 1,
        );
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        if (isComposing || event.nativeEvent.isComposing) {
          return;
        }
        event.preventDefault();
        const selected =
          filteredMentionables[activeIndex] ?? filteredMentionables[0];
        if (selected) {
          selectMention(selected);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setIsFocused(false);
        return;
      }
    }

    if (event.key === "Enter") {
      if (isComposing || event.nativeEvent.isComposing) {
        return;
      }
      if (event.shiftKey) {
        return;
      }
      event.preventDefault();

      const form = event.currentTarget.form;
      const submitButton = form?.querySelector(
        'button[type="submit"]',
      ) as HTMLButtonElement | null;
      if (submitButton?.disabled) {
        return;
      }

      form?.requestSubmit();
      return;
    }

    if (
      event.key === "Backspace" &&
      event.currentTarget.value === "" &&
      attachments.files.length > 0
    ) {
      event.preventDefault();
      const lastAttachment = attachments.files.at(-1);
      if (lastAttachment) {
        attachments.remove(lastAttachment.id);
      }
    }
  };

  const handlePaste: ClipboardEventHandler<HTMLTextAreaElement> = (event) => {
    const items = event.clipboardData?.items;
    if (!items) {
      return;
    }

    const files: File[] = [];
    for (const item of items) {
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      event.preventDefault();
      attachments.add(files);
    }
  };

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setIsFocused(true);
    textInput.setInput(event.currentTarget.value);
    syncSelection(event.currentTarget);
  };

  const selectedSummary = useMemo(() => {
    if (selectedMaterials.length === 0) {
      return null;
    }

    const firstTitle = selectedMaterials[0]?.title?.trim();
    if (!firstTitle) {
      return null;
    }

    return selectedMaterials.length === 1
      ? `已选中【${firstTitle}】本书`
      : `已选中【${firstTitle}】等 ${selectedMaterials.length} 本书`;
  }, [selectedMaterials]);

  return (
    <div className="relative w-full self-stretch">
      {activeMention && (
        <div className="absolute right-0 bottom-[calc(100%+8px)] left-0 z-40">
          <div className="overflow-hidden rounded-2xl border border-[rgba(57,130,152,0.18)] bg-white/97 shadow-lg backdrop-blur-sm">
            <div className="flex items-center gap-2 border-b border-[rgba(57,130,152,0.12)] px-3 py-2 text-xs text-slate-500">
              <LibraryBigIcon className="size-3.5" />
              输入书名后按回车引用，本轮检索将只限制在这些 `@` 书籍内
            </div>
            <Command shouldFilter={false}>
              <CommandList className="max-h-72">
                <CommandEmpty className="py-4 text-sm text-slate-500">
                  没有可引用的已入库书籍
                </CommandEmpty>
                {(["个人知识库", "系统知识库"] as const).map((groupLabel) => {
                  const items = filteredMentionables.filter(
                    (item) => item.groupLabel === groupLabel,
                  );
                  if (items.length === 0) {
                    return null;
                  }

                  return (
                    <CommandGroup key={groupLabel} heading={groupLabel}>
                      {items.map((item) => (
                        <CommandItem
                          key={item.doc_id}
                          value={item.tokenLabel}
                          onMouseDown={(event) => {
                            event.preventDefault();
                          }}
                          onSelect={() => selectMention(item)}
                          className={cn(
                            "items-start gap-3 rounded-xl px-3 py-2.5",
                            filteredMentionables[activeIndex]?.doc_id ===
                              item.doc_id &&
                              "bg-[rgb(241,248,249)] text-[rgb(23,89,108)]",
                          )}
                        >
                          {item.groupLabel === "个人知识库" ? (
                            <FolderIcon className="mt-0.5 size-4 shrink-0" />
                          ) : (
                            <BookOpenTextIcon className="mt-0.5 size-4 shrink-0" />
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium">
                              {item.bookTitle}
                            </div>
                            <div className="truncate text-xs text-slate-500">
                              {item.subtitle}
                            </div>
                          </div>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  );
                })}
              </CommandList>
            </Command>
          </div>
        </div>
      )}
      {selectedSummary && (
        <div className="px-3 pt-3 pb-1">
          <HoverCard openDelay={120}>
            <HoverCardTrigger asChild>
              <button
                type="button"
                className="inline-flex max-w-full items-center rounded-full border border-[rgba(57,130,152,0.18)] bg-[rgb(241,248,249)] px-3 py-1 text-xs font-medium text-[rgb(23,89,108)] transition-colors hover:bg-[rgb(232,244,246)]"
              >
                <span className="truncate">{selectedSummary}</span>
              </button>
            </HoverCardTrigger>
            <HoverCardContent
              align="start"
              className="w-80 rounded-2xl border border-[rgba(57,130,152,0.18)] bg-white/97 p-3 shadow-lg backdrop-blur-sm"
            >
              <div className="mb-2 text-xs font-medium tracking-[0.08em] text-[rgb(23,89,108)] uppercase">
                已选资料范围
              </div>
              <div className="space-y-1.5">
                {selectedMaterials.map((material) => (
                  <div
                    key={material.doc_id}
                    className="rounded-xl bg-[rgb(247,250,251)] px-3 py-2 text-sm text-slate-700"
                  >
                    {material.title}
                  </div>
                ))}
              </div>
            </HoverCardContent>
          </HoverCard>
        </div>
      )}
      <InputGroupTextarea
        ref={textareaRef}
        className={cn(
          "field-sizing-content max-h-48 min-h-16 w-full text-left",
          selectedSummary && "pt-2",
          className,
        )}
        autoFocus={autoFocus}
        disabled={disabled}
        name="message"
        onBlur={(event) => {
          setIsFocused(false);
          syncSelection(event.currentTarget);
        }}
        onChange={handleChange}
        onClick={(event) => {
          setIsFocused(true);
          syncSelection(event.currentTarget);
        }}
        onCompositionEnd={() => setIsComposing(false)}
        onCompositionStart={() => setIsComposing(true)}
        onFocus={() => setIsFocused(true)}
        onKeyDown={handleKeyDown}
        onKeyUp={(event) => {
          setIsFocused(true);
          syncSelection(event.currentTarget);
        }}
        onPaste={handlePaste}
        onSelect={(event) => {
          setIsFocused(true);
          syncSelection(event.currentTarget);
        }}
        placeholder={placeholder}
        value={textInput.value}
      />
    </div>
  );
}
