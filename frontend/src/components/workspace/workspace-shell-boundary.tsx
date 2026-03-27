"use client";

import { WorkspaceShell } from "./workspace-shell";

export function WorkspaceShellBoundary({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
