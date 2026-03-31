"use client";

import { BookOpenTextIcon, MessageSquarePlus, NotebookPenIcon, Settings2Icon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="text-primary block pt-1 font-serif group-hover/workspace-header:hidden">
              DF
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="text-primary ml-2 font-serif">
                财政历史智能知识库
              </Link>
            ) : (
              <div className="text-primary ml-2 cursor-default font-serif">
                财政历史智能知识库
              </div>
            )}
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={
              pathname === "/workspace/knowledge" ||
              pathname.startsWith("/workspace/knowledge/view")
            }
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/knowledge">
              <BookOpenTextIcon size={16} />
              <span>知识库</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
          <>
            <SidebarMenuItem>
              <SidebarMenuButton isActive={pathname === "/workspace/notes"} asChild>
                <Link className="text-muted-foreground" href="/workspace/notes">
                  <NotebookPenIcon size={16} />
                  <span>笔记</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton isActive={pathname === "/workspace/knowledge-manage"} asChild>
                <Link className="text-muted-foreground" href="/workspace/knowledge-manage">
                  <Settings2Icon size={16} />
                  <span>知识库管理</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </>
        )}
      </SidebarMenu>
    </>
  );
}
