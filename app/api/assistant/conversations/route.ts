import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";
import { snapshotForStorage, validSnapshot } from "@/app/assistant/history";

export const dynamic = "force-dynamic";
const json = (value: unknown, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "no-store" } });
const idPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function GET(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return json({ error: "UNAUTHORIZED" }, 401);
  try {
    const url = new URL(request.url), id = url.searchParams.get("id");
    if (id) {
      if (!idPattern.test(id)) return json({ error: "INVALID_REQUEST" }, 400);
      const row = await env.DB.prepare("SELECT id, title, revision, updated_at AS updatedAt, snapshot FROM assistant_conversations WHERE user_id = ? AND id = ?").bind(user.userId, id).first<{ id: string; title: string; revision: number; updatedAt: string; snapshot: string }>();
      return row ? json({ ...row, snapshot: JSON.parse(row.snapshot) }) : json({ error: "NOT_FOUND" }, 404);
    }
    const offset = Number(url.searchParams.get("offset") || 0);
    if (!Number.isSafeInteger(offset) || offset < 0) return json({ error: "INVALID_REQUEST" }, 400);
    const rows = await env.DB.prepare("SELECT id, title, revision, updated_at AS updatedAt FROM assistant_conversations WHERE user_id = ? ORDER BY updated_at DESC, id DESC LIMIT 51 OFFSET ?").bind(user.userId, offset).all();
    return json({ conversations: rows.results.slice(0, 50), hasMore: rows.results.length > 50 });
  } catch { return json({ error: "HISTORY_UNAVAILABLE" }, 503); }
}
export async function PUT(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return json({ error: "UNAUTHORIZED" }, 401);
  if (request.headers.get("origin") !== new URL(request.url).origin) return json({ error: "FORBIDDEN" }, 403);
  try {
    const reader = request.body?.getReader(); if (!reader) return json({ error: "INVALID_REQUEST" }, 400);
    let raw = "", size = 0; const decoder = new TextDecoder();
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.byteLength; if (size > 500000) { await reader.cancel(); return json({ error: "REQUEST_TOO_LARGE" }, 413); }
      raw += decoder.decode(value, { stream: true });
    }
    const body = JSON.parse(raw + decoder.decode());
    if (!body || Object.keys(body).some(k => !["id", "revision", "snapshot"].includes(k)) || !idPattern.test(body.id) || !Number.isSafeInteger(body.revision) || body.revision < 0 || !validSnapshot(body.snapshot)) return json({ error: "INVALID_REQUEST" }, 400);
    const snapshot = snapshotForStorage(body.snapshot);
    const title = (snapshot.messages.find(m => m.role === "user")?.content || snapshot.input || "新对话").replace(/\s+/g, " ").slice(0, 48);
    const updatedAt = new Date().toISOString();
    const row = body.revision === 0
      ? await env.DB.prepare("INSERT INTO assistant_conversations (user_id, id, title, snapshot, revision, updated_at) VALUES (?, ?, ?, ?, 1, ?) ON CONFLICT(user_id,id) DO NOTHING RETURNING revision").bind(user.userId, body.id, title, JSON.stringify(snapshot), updatedAt).first<{ revision: number }>()
      : await env.DB.prepare("UPDATE assistant_conversations SET title = ?, snapshot = ?, revision = revision + 1, updated_at = ? WHERE user_id = ? AND id = ? AND revision = ? RETURNING revision").bind(title, JSON.stringify(snapshot), updatedAt, user.userId, body.id, body.revision).first<{ revision: number }>();
    return row ? json({ id: body.id, title, revision: row.revision, updatedAt }) : json({ error: "HISTORY_CONFLICT" }, 409);
  } catch (e) { return json({ error: e instanceof SyntaxError ? "INVALID_REQUEST" : "HISTORY_UNAVAILABLE" }, e instanceof SyntaxError ? 400 : 503); }
}
