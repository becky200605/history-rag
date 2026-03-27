"use client";

import { ChevronsUpDown, LogOutIcon, Settings2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { startTransition, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { SettingsDialog } from "@/components/workspace/settings";
import { useI18n } from "@/core/i18n/hooks";
import { authClient } from "@/server/better-auth/client";

type WorkspaceUser = {
  name?: string | null;
  email: string;
  image?: string | null;
};

function getUserInitials(user: WorkspaceUser) {
  const source = user.name?.trim() ?? user.email.trim();
  return source.slice(0, 1).toUpperCase();
}

export function WorkspaceUserNav({ user: initialUser }: { user?: WorkspaceUser }) {
  const router = useRouter();
  const { open } = useSidebar();
  const [isPending, setIsPending] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { data: session } = authClient.useSession();
  const { t } = useI18n();
  const user =
    initialUser ??
    (session?.user?.email
      ? {
          email: session.user.email,
          image: session.user.image,
          name: session.user.name,
        }
      : null);

  const handleSignOut = () => {
    startTransition(async () => {
      setIsPending(true);
      const result = await authClient.signOut();
      setIsPending(false);

      if (result.error) {
        toast.error(result.error.message ?? "退出登录失败");
        return;
      }

      router.replace("/auth");
      router.refresh();
    });
  };

  if (!user) {
    return null;
  }

  return (
    <>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <SidebarMenu className="mb-2 w-full">
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size="lg"
                tooltip={!open ? user.email : undefined}
                className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              >
                {open ? (
                  <>
                    <Avatar className="size-8">
                      <AvatarImage
                        src={user.image ?? undefined}
                        alt={user.name ?? user.email}
                      />
                      <AvatarFallback>{getUserInitials(user)}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1 text-left">
                      <p className="truncate text-sm font-medium">
                        {user.name?.trim() ?? "已登录用户"}
                      </p>
                      <p className="text-muted-foreground truncate text-xs">
                        {user.email}
                      </p>
                    </div>
                    <ChevronsUpDown className="text-muted-foreground ml-auto size-4" />
                  </>
                ) : (
                  <div className="flex size-full items-center justify-center">
                    <Avatar className="size-7">
                      <AvatarImage
                        src={user.image ?? undefined}
                        alt={user.name ?? user.email}
                      />
                      <AvatarFallback>{getUserInitials(user)}</AvatarFallback>
                    </Avatar>
                  </div>
                )}
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-64 rounded-lg"
              align="end"
              sideOffset={4}
            >
              <DropdownMenuLabel className="py-2">
                <div className="flex items-center gap-3">
                  <Avatar className="size-8">
                    <AvatarImage
                      src={user.image ?? undefined}
                      alt={user.name ?? user.email}
                    />
                    <AvatarFallback>{getUserInitials(user)}</AvatarFallback>
                  </Avatar>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {user.name?.trim() ?? "已登录用户"}
                    </p>
                    <p className="text-muted-foreground truncate text-xs font-normal">
                      {user.email}
                    </p>
                  </div>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setSettingsOpen(true)}>
                <Settings2Icon />
                {t.common.settings}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={handleSignOut}
                disabled={isPending}
                variant="destructive"
              >
                <LogOutIcon />
                {isPending ? "退出中..." : "退出登录"}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
