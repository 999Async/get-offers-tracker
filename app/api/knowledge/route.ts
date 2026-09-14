import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";
const MAX_BYTES = 8 * 1024 * 1024;
const actions = new Set(["list", "upload", "process", "retrieve", "citation", "facts", "review", "delete", "source", "reconcile"]);

export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  if (!env.AGENT_KNOWLEDGE_URL || !env.AGENT_KNOWLEDGE_TOKEN) {
    return Response.json({ error: "KNOWLEDGE_UNAVAILABLE" }, { status: 503 });
  }
  try {
    if (Number(request.headers.get("content-length")) > MAX_BYTES) return Response.json({ error: "REQUEST_TOO_LARGE" }, { status: 413 });
    const reader = request.body?.getReader();
    if (!reader) return Response.json({ error: "INVALID_REQUEST" }, { status: 400 });
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BYTES) {
        await reader.cancel();
        return Response.json({ error: "REQUEST_TOO_LARGE" }, { status: 413 });
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let input;
    try { input = JSON.parse(new TextDecoder().decode(bytes)); }
    catch { return Response.json({ error: "INVALID_REQUEST" }, { status: 400 }); }
    if (!input || Array.isArray(input) || typeof input !== "object" ||
      Object.keys(input).some((key) => !["action", "payload"].includes(key)) || !actions.has(input.action)) {
      return Response.json({ error: "INVALID_REQUEST" }, { status: 400 });
    }
    const endpoint = new URL("/knowledge", env.AGENT_KNOWLEDGE_URL);
    if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && ["127.0.0.1", "localhost"].includes(endpoint.hostname))) {
      return Response.json({ error: "KNOWLEDGE_UNAVAILABLE" }, { status: 503 });
    }
    const response = await fetch(endpoint, {
      method: "POST", redirect: "manual", signal: AbortSignal.timeout(180_000),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.AGENT_KNOWLEDGE_TOKEN}` },
      body: JSON.stringify({ actor_id: user.userId, tenant_id: user.userId, action: input.action, payload: input.payload ?? {} }),
    });
    if (!response.ok && response.status !== 400) return Response.json({ error: "KNOWLEDGE_UNAVAILABLE" }, { status: 503 });
    return new Response(await response.text(), { status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "KNOWLEDGE_UNAVAILABLE" }, { status: 503 });
  }
}
