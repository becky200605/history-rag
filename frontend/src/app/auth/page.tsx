import { redirect } from "next/navigation";

import { AuthForm } from "@/components/auth/auth-form";
import { env } from "@/env";
import { getSession } from "@/server/better-auth/server";

function resolveNextPath(nextPath: string | string[] | undefined) {
  const candidate = Array.isArray(nextPath) ? nextPath[0] : nextPath;
  if (!candidate || !candidate.startsWith("/")) {
    return "/workspace";
  }
  return candidate;
}

export default async function AuthPage({
  searchParams,
}: {
  searchParams?: Promise<{ next?: string | string[] }>;
}) {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    redirect("/workspace");
  }

  const params = await searchParams;
  const nextPath = resolveNextPath(params?.next);
  const session = await getSession();
  if (session) {
    redirect(nextPath);
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#f4ede2] px-6 py-12">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(160,122,82,0.18),_transparent_34%),radial-gradient(circle_at_bottom,_rgba(214,189,152,0.28),_transparent_30%)]" />
      <div className="absolute inset-0 opacity-35 [background-image:linear-gradient(rgba(82,59,38,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(82,59,38,0.08)_1px,transparent_1px)] [background-size:32px_32px]" />
      <div className="relative z-10 w-full">
        <div className="mx-auto mb-8 max-w-md text-center">
          <p className="text-sm tracking-[0.3em] text-[#8d6e4a] uppercase">
            History RAG
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-[#3f2f1e]">
            财政历史大模型
          </h1>
          <p className="mt-3 text-sm leading-6 text-[#6f5a43]">
            接入 MySQL 用户体系后，工作区访问将基于真实登录态控制。
          </p>
        </div>
        <div className="mx-auto flex max-w-md justify-center">
          <AuthForm />
        </div>
      </div>
    </main>
  );
}
