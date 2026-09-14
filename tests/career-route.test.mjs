import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import ts from "typescript";

function load(path, imports) {
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL("../" + path, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function("require", "exports", source)((name) => { if (!(name in imports)) throw Error(name); return imports[name]; }, exports);
  return exports;
}
const token = "synthetic-test-token-".repeat(3);
const plan = { company: "合成公司", role: "Python 算法", sourceJobId: "job", sourceJobUrl: "https://example.org/jobs/1", resume: "简历.md · 版本 1", resumeDocumentId: "doc", resumeVersionId: "v1", basis_hash: "a".repeat(64) };
function request(body, authorization = "Bearer " + token) {
  return new Request("https://local/api/career", { method: "POST", body: JSON.stringify(body), headers: { authorization } });
}
function fixture() {
  const sqlite = new DatabaseSync(":memory:");
  for (const file of readdirSync(new URL("../drizzle", import.meta.url)).filter((f) => f.endsWith(".sql")).sort()) sqlite.exec(readFileSync(new URL("../drizzle/" + file, import.meta.url), "utf8"));
  const db = {
    prepare(sql) { let values = []; return { bind(...args) { values = args; return this; }, async first() { return sqlite.prepare(sql).get(...values) ?? null; }, async all() { return { results: sqlite.prepare(sql).all(...values) }; }, async run() { return sqlite.prepare(sql).run(...values); } }; },
    async batch(statements) { sqlite.exec("BEGIN"); try { const results = []; for (const statement of statements) results.push(await statement.run()); sqlite.exec("COMMIT"); return results; } catch (e) { sqlite.exec("ROLLBACK"); throw e; } },
  };
  const files = load("app/knowledge/files.ts", {});
  const resume = load("app/api/applications/resume-reference.ts", { "cloudflare:workers": { env: { AGENT_KNOWLEDGE_URL: "http://localhost:8767", AGENT_KNOWLEDGE_TOKEN: token } }, "@/app/knowledge/files": files });
  const route = load("app/api/agent-plans/route.ts", { "cloudflare:workers": { env: { DB: db, AGENT_PRODUCT_TOKEN: token } }, "../applications/resume-reference": resume });
  const call = (action, payload = {}, user = "alice") => route.POST(request({ actor_id: user, tenant_id: user, action, payload }));
  return { sqlite, route, call };
}

test("career proxy binds identity, rejects injection and redirects", async () => {
  const configured = { AGENT_CAREER_URL: "http://localhost:8768", AGENT_CAREER_TOKEN: token };
  const route = (user) => load("app/api/career/route.ts", { "cloudflare:workers": { env: configured }, "@/app/chatgpt-auth": { getChatGPTUser: async () => user } }).POST;
  assert.equal((await route(null)(request({ action: "start" }))).status, 401);
  assert.equal((await route({ userId: "alice" })(request({ action: "get", actor_id: "bob" }))).status, 400);
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.redirect, "manual");
      assert.deepEqual(JSON.parse(options.body), { actor_id: "alice", tenant_id: "alice", action: "get", payload: { run_id: "id" } });
      return Response.json({ run_id: "id" });
    };
    const response = await route({ userId: "alice" })(request({ action: "get", payload: { run_id: "id" } }));
    assert.equal(response.status, 200); assert.equal(response.headers.get("cache-control"), "no-store");
    globalThis.fetch = async () => new Response(null, { status: 302 });
    assert.equal((await route({ userId: "alice" })(request({ action: "get" }))).status, 503);
  } finally { globalThis.fetch = original; }
});

test("product port commits atomically, reads receipt, rejects changed approval and deduplicates jobs", async () => {
  const f = fixture(), original = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    const { tenant_id } = JSON.parse(options.body);
    return Response.json({ documents: tenant_id === "alice" ? [{ document_id: "doc", name: "简历.md", status: "active", versions: [{ version_id: "v1", extension: "md" }] }] : [] });
  };
  try {
    const payload = { idempotency_key: "approved-action", plan };
    const response = await f.call("create", payload);
    assert.equal(response.status, 200, JSON.stringify(await response.clone().json()));
    const saved = await response.json();
    assert.equal((await f.call("lookup", { idempotency_key: "approved-action" })).status, 200);
    assert.deepEqual(await (await f.call("lookup", { idempotency_key: "approved-action" })).json(), saved);
    assert.deepEqual(await (await f.call("lookup", { idempotency_key: "approved-action" }, "bob")).json(), null);
    assert.equal((await f.call("create", { ...payload, plan: { ...plan, role: "changed" } })).status, 409);
    assert.deepEqual(await (await f.call("create", payload)).json(), saved);
    assert.deepEqual(await (await f.call("create", { ...payload, idempotency_key: "second-approved-action" })).json(), saved);
    assert.deepEqual(await (await f.call("create", { idempotency_key: "legacy-id", plan: { ...plan, sourceJobId: "different-import-id" } })).json(), saved);
    const row = f.sqlite.prepare("SELECT * FROM applications").get();
    assert.equal(row.status, "pending"); assert.equal(row.resume_version_id, "v1"); assert.equal(row.user_id, "alice");
    assert.equal(f.sqlite.prepare("SELECT count(*) AS n FROM applications").get().n, 1);
    f.sqlite.exec("DELETE FROM applications");
    globalThis.fetch = async () => { throw Error("file deleted or offline"); };
    assert.deepEqual(await (await f.call("create", payload)).json(), saved);
    assert.equal(f.sqlite.prepare("SELECT count(*) AS n FROM applications").get().n, 0);
  } finally { globalThis.fetch = original; f.sqlite.close(); }
});

test("product port rejects missing service authority, foreign resume and identity changes", async () => {
  const f = fixture(), original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ documents: [] });
  try {
    assert.equal((await f.route.POST(request({ action: "facts" }, ""))).status, 401);
    assert.equal((await f.route.POST(request({ actor_id: "alice", tenant_id: "bob", action: "facts", payload: {} }))).status, 400);
    assert.equal((await f.call("create", { idempotency_key: "foreign", plan })).status, 400);
    assert.equal(f.sqlite.prepare("SELECT count(*) AS n FROM application_plan_receipts").get().n, 0);
    assert.equal(f.sqlite.prepare("SELECT count(*) AS n FROM applications").get().n, 0);
  } finally { globalThis.fetch = original; f.sqlite.close(); }
});
