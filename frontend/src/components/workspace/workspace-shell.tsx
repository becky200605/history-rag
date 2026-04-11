"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { type CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { Toaster } from "sonner";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { useLocalSettings } from "@/core/settings";

const queryClient = new QueryClient();

const workspaceTheme = {
  "--background": "rgb(247 251 252)",
  "--foreground": "rgb(31 41 55)",
  "--card": "rgb(255 255 255)",
  "--card-foreground": "rgb(31 41 55)",
  "--popover": "rgb(255 255 255)",
  "--popover-foreground": "rgb(31 41 55)",
  "--primary": "rgb(57 130 152)",
  "--primary-foreground": "rgb(255 255 255)",
  "--secondary": "rgb(231 242 244)",
  "--secondary-foreground": "rgb(23 89 108)",
  "--muted": "rgb(241 247 249)",
  "--muted-foreground": "rgb(99 115 128)",
  "--accent": "rgb(230 243 246)",
  "--accent-foreground": "rgb(23 89 108)",
  "--border": "rgba(57, 130, 152, 0.16)",
  "--input": "rgba(57, 130, 152, 0.14)",
  "--ring": "rgba(57, 130, 152, 0.18)",
  "--sidebar": "rgb(249 252 252)",
  "--sidebar-foreground": "rgb(31 41 55)",
  "--sidebar-primary": "rgb(57 130 152)",
  "--sidebar-primary-foreground": "rgb(255 255 255)",
  "--sidebar-accent": "rgb(231 244 246)",
  "--sidebar-accent-foreground": "rgb(23 89 108)",
  "--sidebar-border": "rgba(57, 130, 152, 0.14)",
  "--sidebar-ring": "rgba(57, 130, 152, 0.28)",
} as CSSProperties;

type WorkspaceUser = {
  name?: string | null;
  email: string;
  image?: string | null;
};

export function WorkspaceShell({
  children,
  user,
}: Readonly<{ children: React.ReactNode; user?: WorkspaceUser | null }>) {
  const pathname = usePathname();
  const [settings, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(() => !settings.layout.sidebar_collapsed);
  const isImmersiveKnowledgeView = pathname.startsWith("/workspace/knowledge/view");

  useEffect(() => {
    setOpen(!settings.layout.sidebar_collapsed);
  }, [settings.layout.sidebar_collapsed]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      setOpen(nextOpen);
      setSettings("layout", { sidebar_collapsed: !nextOpen });
    },
    [setSettings],
  );

  return (
    <QueryClientProvider client={queryClient}>
      {isImmersiveKnowledgeView ? (
        <div
          className="h-screen bg-[linear-gradient(180deg,rgba(249,252,252,1),rgba(241,248,249,1))] text-foreground"
          style={workspaceTheme}
        >
          {children}
        </div>
      ) : (
        <SidebarProvider
          className="h-screen bg-[linear-gradient(180deg,rgba(249,252,252,1),rgba(241,248,249,1))] text-foreground"
          open={open}
          onOpenChange={handleOpenChange}
          style={workspaceTheme}
        >
          <WorkspaceSidebar user={user} />
          <SidebarInset className="min-w-0 bg-[linear-gradient(180deg,rgba(249,252,252,1),rgba(241,248,249,1))]">
            {children}
          </SidebarInset>
        </SidebarProvider>
      )}
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
