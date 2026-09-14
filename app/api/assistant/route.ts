import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";
function endpoint(path: string) {
  if (!env.AGENT_ASSISTANT_URL || !env.AGENT_ASSISTANT_TOKEN) return null;
  const url = new URL(path, env.AGENT_ASSISTANT_URL);
  if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname)))) return null;
  return url;
}
const error = (reason: string, status: number) => Response.json({ error: reason }, { status, headers: { "Cache-Control": "no-store" } });

export async function GET() {
  if (!await getChatGPTUser()) return error("UNAUTHORIZED", 401);
  try {
    const url = endpoint("/assistant/status");
    if (!url) return Response.json({ configured: false }, { headers: { "Cache-Control": "no-store" } });
    const response = await fetch(url, { headers: { Authorization: `Bearer ${env.AGENT_ASSISTANT_TOKEN}` }, redirect: "manual", signal: AbortSignal.timeout(5000) });
    if (!response.ok) return error("ASSISTANT_UNAVAILABLE", 503);
    const body = await response.json() as { configured?: unknown };
    return Response.json({ configured: body.configured === true }, { headers: { "Cache-Control": "no-store" } });
  } catch { return error("ASSISTANT_UNAVAILABLE", 503); }
}

export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return error("UNAUTHORIZED", 401);
  try {
    const url = endpoint("/assistant");
    if (!url) return error("MODEL_NOT_CONFIGURED", 503);
    const reader = request.body?.getReader();
    if (!reader) return error("INVALID_REQUEST", 400);
    const decoder = new TextDecoder(); let raw = "", size = 0;
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 380000) { await reader.cancel(); return error("REQUEST_TOO_LARGE", 413); }
      raw += decoder.decode(value, { stream: true });
    }
    let body;
    try { body = JSON.parse(raw + decoder.decode()); } catch { return error("INVALID_REQUEST", 400); }
    if (!body || Array.isArray(body) || typeof body !== "object" || Object.keys(body).some((key) => !["request_id", "messages", "materials", "jd"].includes(key))) return error("INVALID_REQUEST", 400);
    const response = await fetch(url, { method: "POST", redirect: "manual",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(310000)]),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.AGENT_ASSISTANT_TOKEN}` },
      body: JSON.stringify({ actor_id: user.userId, tenant_id: user.userId, payload: body }),
    });
    if (!response.ok) return error(response.status === 400 ? "INVALID_REQUEST" : "ASSISTANT_UNAVAILABLE", response.status === 400 ? 400 : 503);
    if (!response.headers.get("content-type")?.includes("application/x-ndjson")) return error("ASSISTANT_UNAVAILABLE", 503);
    return new Response(response.body, { headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
  } catch { return error("ASSISTANT_UNAVAILABLE", 503); }
}
