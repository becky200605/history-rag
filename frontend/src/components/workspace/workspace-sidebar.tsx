"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { RecentChatList } from "./recent-chat-list";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceUserNav } from "./workspace-user-nav";

type WorkspaceUser = {
  name?: string | null;
  email: string;
  image?: string | null;
};

export function WorkspaceSidebar({
  user,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  user?: WorkspaceUser | null;
}) {
  const { open: isSidebarOpen } = useSidebar();
  return (
    <>
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader className="py-0">
          <WorkspaceHeader />
        </SidebarHeader>
        <SidebarContent>
          <WorkspaceNavChatList />
          {isSidebarOpen && <RecentChatList />}
        </SidebarContent>
        <SidebarFooter>
          <WorkspaceUserNav user={user ?? undefined} />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </>
  );
}
