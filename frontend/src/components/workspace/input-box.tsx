"use client";

import type { ChatStatus } from "ai";
import {
  CheckIcon,
  GraduationCapIcon,
  MessageCircleIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  RocketIcon,
  ZapIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
} from "react";

import {
  PromptInput,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputAttachment,
  PromptInputAttachments,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ConfettiButton } from "@/components/ui/confetti-button";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildMentionableKnowledgeMaterials,
  resolveSelectedMaterialsFromMentions,
} from "@/core/knowledge/mentions";
import { useKnowledgeFiles } from "@/core/knowledge/hooks";
import type { SelectedMaterial } from "@/core/knowledge/selection";
import { useUserKnowledgeRecords } from "@/core/knowledge/user-hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { useModels } from "@/core/models/hooks";
import type { AgentScenario, AgentTier } from "@/core/settings/local";
import type { AgentThreadContext } from "@/core/threads";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../ai-elements/model-selector";
import { Suggestion, Suggestions } from "../ai-elements/suggestion";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

import { ModeHoverGuide } from "./mode-hover-guide";
import { KnowledgeMentionTextarea } from "./knowledge-mention-textarea";
import { Tooltip } from "./tooltip";

type ContextShape = Omit<
  AgentThreadContext,
  | "thread_id"
  | "is_plan_mode"
  | "thinking_enabled"
  | "subagent_enabled"
  | "qa_mode"
  | "concise_answers"
> & {
  scenario: AgentScenario;
  tier: AgentTier;
};

function presetLabelKey(
  scenario: AgentScenario,
  tier: AgentTier,
): keyof Pick<
  Translations["inputBox"],
  "researchProLabel" | "researchUltraLabel" | "qaProLabel" | "qaUltraLabel"
> {
  if (scenario === "research" && tier === "ultra") {
    return "researchUltraLabel";
  }
  if (scenario === "qa" && tier === "pro") {
    return "qaProLabel";
  }
  if (scenario === "qa" && tier === "ultra") {
    return "qaUltraLabel";
  }
  return "researchProLabel";
}

function PresetIcon({
  scenario,
  tier,
}: {
  scenario: AgentScenario;
  tier: AgentTier;
}) {
  if (scenario === "research" && tier === "ultra") {
    return <RocketIcon className="size-3 text-[rgb(57,130,152)]" />;
  }
  if (scenario === "qa" && tier === "ultra") {
    return <ZapIcon className="size-3" />;
  }
  if (scenario === "qa" && tier === "pro") {
    return <MessageCircleIcon className="size-3" />;
  }
  return <GraduationCapIcon className="size-3" />;
}

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isNewThread,
  selectedMaterials = [],
  onContextChange,
  onSubmit,
  onStop,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  context: ContextShape;
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  selectedMaterials?: SelectedMaterial[];
  onContextChange?: (context: ContextShape) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const knowledgeFilesQuery = useKnowledgeFiles();
  const userKnowledgeRecordsQuery = useUserKnowledgeRecords();

  const mentionables = useMemo(
    () =>
      buildMentionableKnowledgeMaterials(
        knowledgeFilesQuery.data?.files ?? [],
        userKnowledgeRecordsQuery.data?.records ?? [],
      ),
    [knowledgeFilesQuery.data?.files, userKnowledgeRecordsQuery.data?.records],
  );

  useEffect(() => {
    if (models.length === 0) {
      return;
    }
    const currentModel = models.find((m) => m.name === context.model_name);
    const fallbackModel = currentModel ?? models[0]!;
    const nextModelName = fallbackModel.name;
    if (context.model_name === nextModelName) {
      return;
    }
    onContextChange?.({
      ...context,
      model_name: nextModelName,
    });
  }, [context, models, onContextChange]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);

  const handleModelSelect = useCallback(
    (model_name: string) => {
      const model = models.find((m) => m.name === model_name);
      if (!model) {
        return;
      }
      onContextChange?.({
        ...context,
        model_name,
      });
      setModelDialogOpen(false);
    },
    [onContextChange, context, models],
  );

  const handlePresetSelect = useCallback(
    (scenario: AgentScenario, tier: AgentTier) => {
      onContextChange?.({
        ...context,
        scenario,
        tier,
      });
    },
    [onContextChange, context],
  );

  const triggerLabel = useMemo(
    () => t.inputBox[presetLabelKey(context.scenario, context.tier)],
    [context.scenario, context.tier, t],
  );

  const isPreset = useCallback(
    (scenario: AgentScenario, tier: AgentTier) =>
      context.scenario === scenario && context.tier === tier,
    [context.scenario, context.tier],
  );
  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        onStop?.();
        return;
      }
      const { normalizedText, selectedMaterials } =
        resolveSelectedMaterialsFromMentions(message.text, mentionables);
      const nextText = normalizedText.trim() || message.text.trim();
      if (!nextText) {
        return;
      }
      onSubmit?.({
        ...message,
        text: nextText,
        selectedMaterials:
          selectedMaterials.length > 0 ? selectedMaterials : undefined,
      });
    },
    [mentionables, onSubmit, onStop, status],
  );
  return (
    <PromptInput
      className={cn(
        "bg-background/85 rounded-2xl backdrop-blur-sm transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-2xl",
        className,
      )}
      disabled={disabled}
      globalDrop
      multiple
      onSubmit={handleSubmit}
      {...props}
    >
      {extraHeader && (
        <div className="absolute top-0 right-0 left-0 z-10">
          <div className="absolute right-0 bottom-0 left-0 flex items-center justify-center">
            {extraHeader}
          </div>
        </div>
      )}
      <PromptInputAttachments>
        {(attachment) => <PromptInputAttachment data={attachment} />}
      </PromptInputAttachments>
      <PromptInputBody className="absolute top-0 right-0 left-0 z-3">
        <KnowledgeMentionTextarea
          autoFocus={autoFocus}
          className={cn("size-full")}
          disabled={disabled}
          mentionables={mentionables}
          placeholder={t.inputBox.placeholder}
          selectedMaterials={selectedMaterials}
        />
      </PromptInputBody>
      <PromptInputFooter className="flex">
        <PromptInputTools>
          {/* TODO: Add more connectors here
          <PromptInputActionMenu>
            <PromptInputActionMenuTrigger className="px-2!" />
            <PromptInputActionMenuContent>
              <PromptInputActionAddAttachments
                label={t.inputBox.addAttachments}
              />
            </PromptInputActionMenuContent>
          </PromptInputActionMenu> */}
          <AddAttachmentsButton className="px-2!" />
          <PromptInputActionMenu>
            <ModeHoverGuide scenario={context.scenario} tier={context.tier}>
              <PromptInputActionMenuTrigger className="max-w-38 gap-1! px-2!">
                <PresetIcon scenario={context.scenario} tier={context.tier} />
                <div
                  className={cn(
                    "truncate text-xs font-normal",
                    context.scenario === "research" &&
                      context.tier === "ultra" &&
                      "font-medium text-[rgb(57,130,152)]",
                  )}
                >
                  {triggerLabel}
                </div>
              </PromptInputActionMenuTrigger>
            </ModeHoverGuide>
            <PromptInputActionMenuContent className="w-80">
              <DropdownMenuGroup>
                <DropdownMenuLabel className="text-muted-foreground text-xs">
                  {t.inputBox.mode}
                </DropdownMenuLabel>
                <DropdownMenuLabel className="text-muted-foreground pt-2 text-xs">
                  {t.inputBox.researchScenario}
                </DropdownMenuLabel>
                <PromptInputActionMenu>
                  <PromptInputActionMenuItem
                    className={cn(
                      isPreset("research", "pro")
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handlePresetSelect("research", "pro")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <GraduationCapIcon
                          className={cn(
                            "mr-2 size-4",
                            isPreset("research", "pro") &&
                              "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.researchProLabel}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.researchProDescription}
                      </div>
                    </div>
                    {isPreset("research", "pro") ? (
                      <CheckIcon className="ml-auto size-4 shrink-0" />
                    ) : (
                      <div className="ml-auto size-4 shrink-0" />
                    )}
                  </PromptInputActionMenuItem>
                  <PromptInputActionMenuItem
                    className={cn(
                      isPreset("research", "ultra")
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handlePresetSelect("research", "ultra")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <RocketIcon
                          className={cn(
                            "mr-2 size-4",
                            isPreset("research", "ultra") &&
                              "text-[rgb(57,130,152)]",
                          )}
                        />
                        <span
                          className={cn(
                            isPreset("research", "ultra") &&
                              "font-semibold text-[rgb(57,130,152)]",
                          )}
                        >
                          {t.inputBox.researchUltraLabel}
                        </span>
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.researchUltraDescription}
                      </div>
                    </div>
                    {isPreset("research", "ultra") ? (
                      <CheckIcon className="ml-auto size-4 shrink-0" />
                    ) : (
                      <div className="ml-auto size-4 shrink-0" />
                    )}
                  </PromptInputActionMenuItem>
                </PromptInputActionMenu>
                <DropdownMenuSeparator />
                <DropdownMenuLabel className="text-muted-foreground text-xs">
                  {t.inputBox.qaScenario}
                </DropdownMenuLabel>
                <PromptInputActionMenu>
                  <PromptInputActionMenuItem
                    className={cn(
                      isPreset("qa", "pro")
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handlePresetSelect("qa", "pro")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <MessageCircleIcon
                          className={cn(
                            "mr-2 size-4",
                            isPreset("qa", "pro") && "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.qaProLabel}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.qaProDescription}
                      </div>
                    </div>
                    {isPreset("qa", "pro") ? (
                      <CheckIcon className="ml-auto size-4 shrink-0" />
                    ) : (
                      <div className="ml-auto size-4 shrink-0" />
                    )}
                  </PromptInputActionMenuItem>
                  <PromptInputActionMenuItem
                    className={cn(
                      isPreset("qa", "ultra")
                        ? "text-accent-foreground"
                        : "text-muted-foreground/65",
                    )}
                    onSelect={() => handlePresetSelect("qa", "ultra")}
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1 font-bold">
                        <ZapIcon
                          className={cn(
                            "mr-2 size-4",
                            isPreset("qa", "ultra") && "text-accent-foreground",
                          )}
                        />
                        {t.inputBox.qaUltraLabel}
                      </div>
                      <div className="pl-7 text-xs">
                        {t.inputBox.qaUltraDescription}
                      </div>
                    </div>
                    {isPreset("qa", "ultra") ? (
                      <CheckIcon className="ml-auto size-4 shrink-0" />
                    ) : (
                      <div className="ml-auto size-4 shrink-0" />
                    )}
                  </PromptInputActionMenuItem>
                </PromptInputActionMenu>
              </DropdownMenuGroup>
            </PromptInputActionMenuContent>
          </PromptInputActionMenu>
        </PromptInputTools>
        <PromptInputTools>
          <ModelSelector
            open={modelDialogOpen}
            onOpenChange={setModelDialogOpen}
          >
            <ModelSelectorTrigger asChild>
              <PromptInputButton>
                <ModelSelectorName className="text-xs font-normal">
                  {selectedModel?.display_name}
                </ModelSelectorName>
              </PromptInputButton>
            </ModelSelectorTrigger>
            <ModelSelectorContent>
              <ModelSelectorInput placeholder={t.inputBox.searchModels} />
              <ModelSelectorList>
                {models.map((m) => (
                  <ModelSelectorItem
                    key={m.name}
                    value={m.name}
                    onSelect={() => handleModelSelect(m.name)}
                  >
                    <ModelSelectorName>{m.display_name}</ModelSelectorName>
                    {m.name === context.model_name ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </ModelSelectorItem>
                ))}
              </ModelSelectorList>
            </ModelSelectorContent>
          </ModelSelector>
          <PromptInputSubmit
            className="rounded-full"
            disabled={disabled}
            variant="outline"
            status={status}
          />
        </PromptInputTools>
      </PromptInputFooter>
      {isNewThread && searchParams.get("mode") !== "skill" && (
        <div className="absolute right-0 -bottom-20 left-0 z-0 flex items-center justify-center">
          <SuggestionList />
        </div>
      )}
      {!isNewThread && (
        <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
      )}
    </PromptInput>
  );
}

function SuggestionList() {
  const { t } = useI18n();
  const { textInput } = usePromptInputController();
  const handleSuggestionClick = useCallback(
    (prompt: string | undefined) => {
      if (!prompt) return;
      textInput.setInput(prompt);
      setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='message']",
        );
        if (textarea) {
          const selStart = prompt.indexOf("[");
          const selEnd = prompt.indexOf("]");
          if (selStart !== -1 && selEnd !== -1) {
            textarea.setSelectionRange(selStart, selEnd + 1);
            textarea.focus();
          }
        }
      }, 500);
    },
    [textInput],
  );
  return (
    <Suggestions className="min-h-16 w-fit items-start">
      <ConfettiButton
        className="text-muted-foreground cursor-pointer rounded-full px-4 text-xs font-normal"
        variant="outline"
        size="sm"
        onClick={() => handleSuggestionClick(t.inputBox.surpriseMePrompt)}
      >
        <SparklesIcon className="size-4" /> {t.inputBox.surpriseMe}
      </ConfettiButton>
      {t.inputBox.suggestions.map((suggestion) => (
        <Suggestion
          key={suggestion.suggestion}
          icon={suggestion.icon}
          suggestion={suggestion.suggestion}
          onClick={() => handleSuggestionClick(suggestion.prompt)}
        />
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Suggestion icon={PlusIcon} suggestion={t.common.create} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuGroup>
            {t.inputBox.suggestionsCreate.map((suggestion, index) =>
              "type" in suggestion && suggestion.type === "separator" ? (
                <DropdownMenuSeparator key={index} />
              ) : (
                !("type" in suggestion) && (
                  <DropdownMenuItem
                    key={suggestion.suggestion}
                    onClick={() => handleSuggestionClick(suggestion.prompt)}
                  >
                    {suggestion.icon && <suggestion.icon className="size-4" />}
                    {suggestion.suggestion}
                  </DropdownMenuItem>
                )
              ),
            )}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </Suggestions>
  );
}

function AddAttachmentsButton({ className }: { className?: string }) {
  const { t } = useI18n();
  const attachments = usePromptInputAttachments();
  return (
    <Tooltip content={t.inputBox.addAttachments}>
      <PromptInputButton
        className={cn("px-2!", className)}
        onClick={() => attachments.openFileDialog()}
      >
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}
