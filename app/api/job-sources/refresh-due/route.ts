import { env } from "cloudflare:workers";
import { refreshDue } from "@/app/job-sources/store";
export async function POST(request: Request) {
  const token = env.AGENT_SEARCH_TOKEN;
  if (!token || token.length < 32) return new Response(null, { status: 503 });
  const encode = (value: string) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  const [given, expected] = await Promise.all([encode(request.headers.get("authorization") || ""), encode(`Bearer ${token}`)]);
  if (!new Uint8Array(given).every((byte, i) => byte === new Uint8Array(expected)[i])) return new Response(null, { status: 401 });
  return Response.json({ checked: await refreshDue(env.DB) }, { headers: { "Cache-Control": "no-store" } });
}
