import type { NextRequest } from "next/server";

import { env } from "@/env";
import { auth } from "@/server/better-auth";

export const dynamic = "force-dynamic";

const DEFAULT_LANGGRAPH_BASE_URL = "http://127.0.0.1:2024";
const JSON_CONTENT_TYPE = "application/json";
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

type AuthenticatedSession = NonNullable<
  Awaited<ReturnType<typeof auth.api.getSession>>
>;

function getMetadataRecord(body?: Record<string, unknown>) {
  const metadata = body?.metadata;
  return metadata && typeof metadata === "object"
    ? (metadata as Record<string, unknown>)
    : {};
}

function getUpstreamBaseUrl() {
  return process.env.LANGGRAPH_BASE_URL ??
    process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL ??
    DEFAULT_LANGGRAPH_BASE_URL;
}

function buildUpstreamUrl(path: string[], request: NextRequest) {
  const url = new URL(path.join("/"), `${getUpstreamBaseUrl()}/`);
  url.search = request.nextUrl.search;
  return url;
}

function buildForwardHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function parseRequestBody(request: NextRequest) {
  if (request.method === "GET" || request.method === "HEAD") {
    return { rawBody: undefined, jsonBody: undefined as unknown };
  }

  const rawBody = await request.text();
  const contentType = request.headers.get("content-type") ?? "";
  if (!rawBody || !contentType.includes(JSON_CONTENT_TYPE)) {
    return { rawBody, jsonBody: undefined as unknown };
  }

  return {
    rawBody,
    jsonBody: JSON.parse(rawBody) as Record<string, unknown>,
  };
}

function serializeBody(body: unknown, fallbackRawBody?: string) {
  if (body === undefined) {
    return fallbackRawBody;
  }
  return JSON.stringify(body);
}

function jsonResponse(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": `${JSON_CONTENT_TYPE}; charset=utf-8`,
    },
  });
}

function upstreamUnavailableResponse(error: unknown) {
  const message =
    error instanceof Error ? error.message : "Unable to reach LangGraph upstream";
  return jsonResponse(
    {
      message: "LangGraph upstream unavailable",
      detail: message,
      upstream: getUpstreamBaseUrl(),
    },
    502,
  );
}

async function getAuthenticatedSession(request: NextRequest) {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return null;
  }

  return auth.api.getSession({
    headers: request.headers,
  });
}

async function fetchUpstreamThread(threadId: string) {
  const response = await fetch(`${getUpstreamBaseUrl()}/threads/${threadId}`, {
    headers: {
      accept: JSON_CONTENT_TYPE,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    return {
      response,
      thread: null as null | Record<string, unknown>,
    };
  }

  return {
    response,
    thread: (await response.json()) as Record<string, unknown>,
  };
}

async function ensureThreadOwnership(
  threadId: string,
  session: AuthenticatedSession,
) {
  const { response, thread } = await fetchUpstreamThread(threadId);
  if (!response.ok || !thread) {
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  }

  const metadata =
    thread.metadata && typeof thread.metadata === "object"
      ? (thread.metadata as Record<string, unknown>)
      : {};
  const ownerId =
    typeof metadata.user_id === "string" ? metadata.user_id : undefined;

  if (!ownerId) {
    const claimResponse = await fetch(
      `${getUpstreamBaseUrl()}/threads/${threadId}`,
      {
        method: "PATCH",
        headers: {
          "content-type": JSON_CONTENT_TYPE,
          accept: JSON_CONTENT_TYPE,
        },
        body: JSON.stringify({
          metadata: {
            ...metadata,
            user_id: session.user.id,
          },
        }),
      },
    );

    if (!claimResponse.ok) {
      return new Response(claimResponse.body, {
        status: claimResponse.status,
        headers: claimResponse.headers,
      });
    }

    return null;
  }

  if (ownerId !== session.user.id) {
    return jsonResponse({ message: "Forbidden" }, 403);
  }

  return null;
}

function isThreadScopedPath(path: string[]) {
  return (
    path[0] === "threads" &&
    typeof path[1] === "string" &&
    path[1] !== "search" &&
    path[1] !== "count"
  );
}

async function proxyToLangGraph(request: NextRequest, path: string[]) {
  try {
    const session = await getAuthenticatedSession(request);
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && !session) {
      return jsonResponse({ message: "Unauthorized" }, 401);
    }

    const { rawBody, jsonBody } = await parseRequestBody(request);
    let nextJsonBody = jsonBody as Record<string, unknown> | undefined;

    if (session && path[0] === "threads" && request.method === "POST") {
      if (path.length === 1) {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      } else if (path[1] === "search" || path[1] === "count") {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      }
    }

    if (session && isThreadScopedPath(path)) {
      const ownershipResponse = await ensureThreadOwnership(path[1]!, session);
      if (ownershipResponse) {
        return ownershipResponse;
      }

      if (
        request.method === "PATCH" &&
        (path.length === 2 || (path.length === 3 && path[2] === "state"))
      ) {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      }
    }

    const upstreamResponse = await fetch(buildUpstreamUrl(path, request), {
      method: request.method,
      headers: buildForwardHeaders(request),
      body: serializeBody(nextJsonBody, rawBody),
      cache: "no-store",
    });

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: upstreamResponse.headers,
    });
  } catch (error) {
    return upstreamUnavailableResponse(error);
  }
}

async function handleRequest(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxyToLangGraph(request, path);
}

export async function GET(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}
