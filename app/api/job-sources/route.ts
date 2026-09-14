import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";
import { createSource, listSources, refreshSource } from "@/app/job-sources/store";
import type { SourceJob } from "@/app/job-sources/importer";
export const dynamic = "force-dynamic";
const json = (body: unknown, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
export async function GET() {
  const user = await getChatGPTUser(); if (!user) return json({ error: "请先登录" }, 401);
  try { return json({ sources: await listSources(env.DB, user.userId) }); } catch { return json({ error: "暂时无法读取数据源" }, 503); }
}
export async function POST(request: Request) {
  const user = await getChatGPTUser(); if (!user) return json({ error: "请先登录" }, 401);
  if (request.headers.get("origin") !== new URL(request.url).origin) return json({ error: "请求来源无效" }, 403);
  try {
    let addedJobs: SourceJob[] = [];
    let refreshSucceeded: boolean | undefined;
    const reader = request.body?.getReader(); if (!reader) return json({ error: "无效请求" }, 400);
    let raw = "", size = 0; const decoder = new TextDecoder();
    for (;;) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > 4096) { await reader.cancel(); return json({ error: "内容过长" }, 413); } raw += decoder.decode(value, { stream: true }); }
    const body = JSON.parse(raw + decoder.decode());
    if (!body || Object.keys(body).some(key => !["action", "id", "name", "url", "enabled"].includes(key))) return json({ error: "无效请求" }, 400);
    if (body.action === "add") {
      if (typeof body.name !== "string" || typeof body.url !== "string") return json({ error: "请填写名称和链接" }, 400);
      const id = await createSource(env.DB, user.userId, body.name, body.url);
      const result = await refreshSource(env.DB, user.userId, id); if (result) { addedJobs = result.addedJobs; refreshSucceeded = result.succeeded; }
    } else {
      if (typeof body.id !== "string" || body.id.length > 100) return json({ error: "无效请求" }, 400);
      const found = await env.DB.prepare("SELECT id FROM radar_sources WHERE user_id=? AND id=?").bind(user.userId, body.id).first();
      if (!found) return json({ error: "数据源不存在" }, 404);
      if (body.action === "refresh") { const result = await refreshSource(env.DB, user.userId, body.id); if (result) { addedJobs = result.addedJobs; refreshSucceeded = result.succeeded; } }
      else if (body.action === "remove") await env.DB.prepare("DELETE FROM radar_sources WHERE user_id=? AND id=?").bind(user.userId, body.id).run();
      else if (body.action === "schedule" && typeof body.enabled === "boolean") await env.DB.prepare("UPDATE radar_sources SET enabled=?, next_run=?, lease_token='', lease_until=0 WHERE user_id=? AND id=?").bind(body.enabled ? 1 : 0, Date.now(), user.userId, body.id).run();
      else return json({ error: "无效请求" }, 400);
    }
    return json({ sources: await listSources(env.DB, user.userId), addedJobs, refreshSucceeded });
  } catch (error) { return json({ error: error instanceof Error && /^[\u4e00-\u9fff]/.test(error.message) ? error.message : "操作失败，请稍后重试" }, 400); }
}
