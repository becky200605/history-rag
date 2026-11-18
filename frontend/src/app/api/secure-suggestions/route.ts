import type { NextRequest } from "next/server";

import { env } from "@/env";
import { auth } from "@/server/better-auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
    const session = await auth.api.getSession({ headers: request.headers });
    if (!session)
      return Response.json({ message: "Unauthorized" }, { status: 401 });
  }
  try {
    const body = (await request.json()) as {
      question?: unknown;
      answer?: unknown;
    };
    if (
      typeof body.question !== "string" ||
      !body.question.trim() ||
      body.question.length > 4000 ||
      typeof body.answer !== "string" ||
      !body.answer.trim() ||
      body.answer.length > 24000
    ) {
      return Response.json(
        { message: "Invalid question or answer" },
        { status: 400 },
      );
    }
    const base =
      process.env.BACKEND_BASE_URL ??
      env.NEXT_PUBLIC_BACKEND_BASE_URL ??
      "http://127.0.0.1:8001";
    const upstream = await fetch(new URL("/api/models/suggestions", base), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: body.question, answer: body.answer }),
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ questions: [] }, { status: 502 });
  }
}
