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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden font-serif px-6 py-12">
      <div
        className="absolute inset-0 z-0 bg-cover bg-center bg-no-repeat"
        style={{
          backgroundImage: 'url("/historical_parchment_bg.png")',
          filter: "brightness(0.7)",
        }}
      />
      <div className="absolute inset-0 z-0 bg-black/30" />
      <div className="relative z-10 w-full mb-12">
        <div className="mx-auto mb-12 max-w-md text-center">
          <h1 className="mt-3 text-5xl font-bold tracking-widest text-[#fdf6e3] drop-shadow-lg">
            财政历史智能知识库
          </h1>
          <p className="mt-4 text-lg font-medium tracking-[0.2em] text-[#fdf6e3]/80 uppercase drop-shadow-md">
            History RAG System
          </p>
        </div>
        <div className="mx-auto flex max-w-md justify-center">
          <AuthForm />
        </div>
      </div>
    </main>
  );
}
