"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Toaster } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { useLocalSettings } from "@/core/settings";
import { env } from "@/env";

const queryClient = new QueryClient();

export default function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [settings, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(() => !settings.layout.sidebar_collapsed);
  const [inviteChecked, setInviteChecked] = useState(false);
  const [inviteVerified, setInviteVerified] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [inviteError, setInviteError] = useState("");

  useEffect(() => {
    setOpen(!settings.layout.sidebar_collapsed);
  }, [settings.layout.sidebar_collapsed]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem("workspace.invite_verified");
    if (stored === "1") {
      setInviteVerified(true);
    }
    setInviteChecked(true);
  }, []);

  const handleInviteSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = inviteCode.trim();
    if (!trimmed) {
      setInviteError("请输入有效的邀请码");
      return;
    }

    const configuredCode = env.NEXT_PUBLIC_INVITE_CODE;
    if (configuredCode && trimmed !== configuredCode) {
      setInviteError("邀请码不正确，请确认后再试");
      return;
    }

    if (typeof window !== "undefined") {
      window.localStorage.setItem("workspace.invite_verified", "1");
    }
    setInviteVerified(true);
    setInviteError("");
  };

  const handleOpenChange = useCallback(
    (open: boolean) => {
      setOpen(open);
      setSettings("layout", { sidebar_collapsed: !open });
    },
    [setSettings],
  );

  if (!inviteChecked) {
    return null;
  }

  return (
    <QueryClientProvider client={queryClient}>
      {inviteVerified ? (
        <SidebarProvider
          className="h-screen"
          open={open}
          onOpenChange={handleOpenChange}
        >
          <WorkspaceSidebar />
          <SidebarInset className="min-w-0">{children}</SidebarInset>
        </SidebarProvider>
      ) : (
        <div className="flex h-screen w-full items-center justify-center bg-background">
          <form
            onSubmit={handleInviteSubmit}
            className="bg-card text-card-foreground border-input/60 w-full max-w-md rounded-xl border px-8 py-10 shadow-lg"
          >
            <div className="mb-6 space-y-1">
              <h1 className="text-2xl font-semibold">请输入邀请码</h1>
              <p className="text-muted-foreground text-sm">
                当前处于内测阶段，仅向受邀用户开放工作区访问。
              </p>
            </div>
            <div className="space-y-2">
              <Input
                autoFocus
                placeholder="请输入邀请码"
                value={inviteCode}
                onChange={(event) => {
                  setInviteCode(event.target.value);
                  if (inviteError) {
                    setInviteError("");
                  }
                }}
                aria-invalid={!!inviteError}
              />
              {inviteError ? (
                <p className="text-destructive text-sm">{inviteError}</p>
              ) : null}
            </div>
            <Button type="submit" className="mt-6 w-full">
              确认进入工作区
            </Button>
          </form>
        </div>
      )}
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
