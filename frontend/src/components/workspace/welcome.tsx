"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { AgentScenario, AgentTier } from "@/core/settings/local";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

export function Welcome({
  className,
  scenario,
  tier,
}: {
  className?: string;
  scenario?: AgentScenario;
  tier?: AgentTier;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const isResearchUltra = useMemo(
    () => scenario === "research" && tier === "ultra",
    [scenario, tier],
  );
  const colors = useMemo(() => {
    if (isResearchUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isResearchUltra]);
  useEffect(() => {
    waved = true;
  }, []);
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="text-2xl font-bold">
        {searchParams.get("mode") === "skill" ? (
          `✨ ${t.welcome.createYourOwnSkill} ✨`
        ) : (
            <div className="flex items-center gap-2">
            <div className={cn("inline-block", !waved ? "animate-wave" : "")}>
              {isResearchUltra ? "🚀" : "👋"}
            </div>
            <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
          </div>
        )}
      </div>
      {searchParams.get("mode") === "skill" ? (
        <div className="text-muted-foreground text-sm">
          {t.welcome.createYourOwnSkillDescription.includes("\n") ? (
            <pre className="font-sans whitespace-pre">
              {t.welcome.createYourOwnSkillDescription}
            </pre>
          ) : (
            <p>{t.welcome.createYourOwnSkillDescription}</p>
          )}
        </div>
      ) : (
        <div className="text-muted-foreground text-sm">
          {t.welcome.description.includes("\n") ? (
            <pre className="whitespace-pre">{t.welcome.description}</pre>
          ) : (
            <p>{t.welcome.description}</p>
          )}
        </div>
      )}
    </div>
  );
}
