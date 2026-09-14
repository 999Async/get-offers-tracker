import { env } from "cloudflare:workers";

import { getChatGPTUser } from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  if (!env.AGENT_SEARCH_URL || !env.AGENT_SEARCH_TOKEN) {
    return Response.json({ error: "JOB_SEARCH_UNAVAILABLE" }, { status: 503 });
  }
  try {
    const declared = Number(request.headers.get("content-length") || 0);
    if (declared > 16_384) return Response.json({ error: "REQUEST_TOO_LARGE" }, { status: 413 });
    const raw = await request.text();
    if (new TextEncoder().encode(raw).byteLength > 16_384) {
      return Response.json({ error: "REQUEST_TOO_LARGE" }, { status: 413 });
    }
    let input: unknown;
    try { input = JSON.parse(raw); }
    catch { return Response.json({ error: "INVALID_SEARCH_REQUEST" }, { status: 400 }); }
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      return Response.json({ error: "INVALID_SEARCH_REQUEST" }, { status: 400 });
    }
    const allowed = new Set(["query", "hard_constraints", "soft_preferences", "top_k", "candidate_profile_version"]);
    if (Object.keys(input).some((key) => !allowed.has(key))) {
      return Response.json({ error: "INVALID_SEARCH_REQUEST" }, { status: 400 });
    }
    const endpoint = new URL("/search", env.AGENT_SEARCH_URL);
    if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" &&
      ["127.0.0.1", "localhost"].includes(endpoint.hostname))) {
      return Response.json({ error: "JOB_SEARCH_UNAVAILABLE" }, { status: 503 });
    }
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.AGENT_SEARCH_TOKEN}` },
      body: JSON.stringify({ actor_id: user.userId, tenant_id: user.userId, request: input }),
      signal: AbortSignal.timeout(30_000),
      redirect: "error",
    });
    if (!response.ok) {
      return Response.json({ error: response.status === 400 ? "INVALID_SEARCH_REQUEST" : "JOB_SEARCH_UNAVAILABLE" },
        { status: response.status === 400 ? 400 : 503 });
    }
    return new Response(await response.text(), {
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "JOB_SEARCH_UNAVAILABLE" }, { status: 503 });
  }
}
