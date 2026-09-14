import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";
const actions = new Set(["start", "get", "status", "resume", "propose", "decide", "cancel"]);

export async function POST(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  if (!env.AGENT_CAREER_URL || !env.AGENT_CAREER_TOKEN) return Response.json({ error: "CAREER_UNAVAILABLE" }, { status: 503 });
  try {
    const reader = request.body?.getReader();
    if (!reader) return Response.json({ error: "INVALID_REQUEST" }, { status: 400 });
    let raw = "", length = 0;
    const decoder = new TextDecoder();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 16384) { await reader.cancel(); return Response.json({ error: "REQUEST_TOO_LARGE" }, { status: 413 }); }
      raw += decoder.decode(value, { stream: true });
    }
    let input;
    try { input = JSON.parse(raw + decoder.decode()); } catch { return Response.json({ error: "INVALID_REQUEST" }, { status: 400 }); }
    if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).some((key) => !["action", "payload"].includes(key)) || !actions.has(input.action)) {
      return Response.json({ error: "INVALID_REQUEST" }, { status: 400 });
    }
    const endpoint = new URL("/career", env.AGENT_CAREER_URL);
    if (endpoint.username || endpoint.password || (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && ["localhost", "127.0.0.1"].includes(endpoint.hostname)))) throw new Error("configuration");
    const response = await fetch(endpoint, {
      method: "POST", redirect: "manual", signal: AbortSignal.timeout(180_000),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.AGENT_CAREER_TOKEN}` },
      body: JSON.stringify({ actor_id: user.userId, tenant_id: user.userId, action: input.action, payload: input.payload ?? {} }),
    });
    if (![200, 400, 403].includes(response.status)) throw new Error("unavailable");
    return new Response(await response.text(), { status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch { return Response.json({ error: "CAREER_UNAVAILABLE" }, { status: 503 }); }
}
