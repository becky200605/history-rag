import { redirect } from "next/navigation";

import { AuthForm } from "@/components/auth/auth-form";
import { env } from "@/env";
import { getSession } from "@/server/better-auth/server";

function resolveNextPath(nextPath: string | string[] | undefined) {
  const candidate = Array.isArray(nextPath) ? nextPath[0] : nextPath;
  if (candidate?.startsWith("/") !== true) {
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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[rgb(244,249,250)] px-6 py-12">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(57,130,152,0.22),_transparent_34%),radial-gradient(circle_at_bottom,_rgba(57,130,152,0.14),_transparent_30%)]" />
      <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(57,130,152,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(57,130,152,0.08)_1px,transparent_1px)] [background-size:32px_32px]" />
      <div className="relative z-10 w-full">
        <div className="mx-auto mb-8 max-w-md text-center">
          <p className="text-sm tracking-[0.3em] text-[rgb(57,130,152)] uppercase">
            History RAG
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-[rgb(23,89,108)]">
            财政历史智能知识库
          </h1>
        </div>
        <div className="mx-auto flex max-w-md justify-center">
          <AuthForm />
        </div>
      </div>
    </main>
  );
}
