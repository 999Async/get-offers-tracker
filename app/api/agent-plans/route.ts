import { env } from "cloudflare:workers";
import { userResumeFiles, validateResumeReference } from "../applications/resume-reference";

export const dynamic = "force-dynamic";
async function hash(value: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), (v) => v.toString(16).padStart(2, "0")).join("");
}
function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function text(value: unknown, max: number): value is string { return typeof value === "string" && value.trim().length > 0 && value.length <= max; }
type Receipt = { plan_id: string; arguments_hash: string };

export async function POST(request: Request) {
  const token = env.AGENT_PRODUCT_TOKEN;
  // Hash both strings before comparing: fixed-length comparison and no token logging.
  if (!token || token.length < 32 || await hash(request.headers.get("authorization") ?? "") !== await hash(`Bearer ${token}`)) {
    return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  }
  const respond = (data: unknown, status = 200) => Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
  try {
    if (!env.DB) throw new Error("unavailable");
    const reader = request.body?.getReader();
    if (!reader) return respond({ error: "INVALID_REQUEST" }, 400);
    const chunks: Uint8Array[] = []; let length = 0;
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      length += value.byteLength;
      if (length > 16384) { await reader.cancel(); return respond({ error: "REQUEST_TOO_LARGE" }, 413); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let body;
    try { body = JSON.parse(new TextDecoder().decode(bytes)); } catch { return respond({ error: "INVALID_REQUEST" }, 400); }
    if (!object(body) || Object.keys(body).some((k) => !["actor_id", "tenant_id", "action", "payload"].includes(k)) ||
        !text(body.actor_id, 300) || body.actor_id !== body.tenant_id || !object(body.payload)) return respond({ error: "INVALID_REQUEST" }, 400);
    const userId = body.actor_id, payload = body.payload, db = env.DB;
    if (body.action === "facts") {
      if (Object.keys(payload).length) return respond({ error: "INVALID_REQUEST" }, 400);
      const rows = await db.prepare("SELECT source_job_id, source_job_url, id FROM applications WHERE user_id=?").bind(userId).all<{ source_job_id: string; source_job_url: string; id: string }>();
      return respond({ by_job: Object.fromEntries(rows.results.filter((r: { source_job_id: string }) => r.source_job_id).map((r: { source_job_id: string; id: string }) => [r.source_job_id, r.id])),
        by_url: Object.fromEntries(rows.results.filter((r: { source_job_url: string }) => r.source_job_url).map((r: { source_job_url: string; id: string }) => [r.source_job_url, r.id])) });
    }
    const key = payload.idempotency_key;
    if (!text(key, 200) || Object.keys(payload).some((k) => !["idempotency_key", ...(body.action === "create" ? ["plan"] : [])].includes(k))) return respond({ error: "INVALID_REQUEST" }, 400);
    const lookup = () => db.prepare("SELECT plan_id, arguments_hash FROM application_plan_receipts WHERE user_id=? AND idempotency_key=?").bind(userId, key).first<Receipt>();
    if (body.action === "lookup") { const receipt = await lookup(); return respond(receipt ? { plan_id: receipt.plan_id } : null); }
    if (body.action !== "create" || !object(payload.plan)) return respond({ error: "INVALID_REQUEST" }, 400);
    const plan = payload.plan;
    const limits: Record<string, number> = { company: 300, role: 500, sourceJobId: 200, sourceJobUrl: 2000, resume: 300, resumeDocumentId: 100, resumeVersionId: 100, basis_hash: 64 };
    if (Object.keys(plan).length !== Object.keys(limits).length || Object.entries(limits).some(([k, max]) => !text(plan[k], max)) || !/^[a-f0-9]{64}$/.test(String(plan.basis_hash))) return respond({ error: "INVALID_REQUEST" }, 400);
    const source = new URL(String(plan.sourceJobUrl));
    if (!["https:", "http:"].includes(source.protocol) || source.username || source.password) return respond({ error: "INVALID_REQUEST" }, 400);
    const argumentsHash = await hash(JSON.stringify(Object.fromEntries(Object.keys(plan).sort().map((k) => [k, plan[k]]))));
    const previous = await lookup();
    if (previous) return previous.arguments_hash === argumentsHash ? respond({ plan_id: previous.plan_id }) : respond({ error: "IDEMPOTENCY_CONFLICT" }, 409);
    const reference = { resume: String(plan.resume), resumeDocumentId: String(plan.resumeDocumentId), resumeVersionId: String(plan.resumeVersionId) };
    await validateResumeReference(reference, undefined, () => userResumeFiles(userId));
    if (reference.resume !== plan.resume) return respond({ error: "RESUME_CHANGED" }, 409);
    const attempt = crypto.randomUUID(), newId = crypto.randomUUID(), now = new Date().toISOString();
    // D1 batch is a transaction. Only the receipt creator can insert a plan. A retry,
    // including one after the user deleted the application, cannot recreate it.
    await db.batch([
      db.prepare("INSERT INTO application_plan_receipts (user_id,idempotency_key,arguments_hash,plan_id,attempt_id,created_at) VALUES (?,?,?,COALESCE((SELECT id FROM applications WHERE user_id=? AND (source_job_id=? OR source_job_url=?) LIMIT 1),?),?,?) ON CONFLICT(user_id,idempotency_key) DO NOTHING")
        .bind(userId, key, argumentsHash, userId, plan.sourceJobId, plan.sourceJobUrl, newId, attempt, now),
      db.prepare("INSERT INTO applications (user_id,id,company,role,status,resume,resume_document_id,resume_version_id,source_job_id,source_job_url,created_at,updated_at) SELECT user_id,plan_id,?,?,'pending',?,?,?,?,?,?,? FROM application_plan_receipts WHERE user_id=? AND idempotency_key=? AND attempt_id=? ON CONFLICT(user_id,id) DO NOTHING")
        .bind(plan.company, plan.role, plan.resume, plan.resumeDocumentId, plan.resumeVersionId, plan.sourceJobId, plan.sourceJobUrl, now, now, userId, key, attempt),
    ]);
    const saved = await lookup();
    if (!saved || saved.arguments_hash !== argumentsHash) return respond({ error: "IDEMPOTENCY_CONFLICT" }, 409);
    return respond({ plan_id: saved.plan_id });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "";
    return respond({ error: reason === "INVALID_RESUME_REFERENCE" ? reason : "PLAN_UNAVAILABLE" }, reason === "INVALID_RESUME_REFERENCE" ? 400 : 503);
  }
}
