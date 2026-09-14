import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";
const source = fs.readFileSync(new URL("../app/api/knowledge/route.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function route(user, env = {}) {
  const exports = {};
  const require = (name) => name === "cloudflare:workers" ? { env } : { getChatGPTUser: async () => user };
  new Function("require", "exports", compiled)(require, exports);
  return exports.POST;
}
function request(body) { return new Request("https://getoffers.example/api/knowledge", { method: "POST", body: JSON.stringify(body) }); }
const configured = { AGENT_KNOWLEDGE_URL: "http://127.0.0.1:8767", AGENT_KNOWLEDGE_TOKEN: "local-test-token" };
test("knowledge requires product authentication and configured service", async () => {
  assert.equal((await route(null)(request({ action: "list" }))).status, 401);
  assert.equal((await route({ userId: "alice" })(request({ action: "list" }))).status, 503);
});
test("knowledge rejects identity injection, unknown actions and oversized streams", async () => {
  const post = route({ userId: "alice" }, configured);
  for (const body of [{ action: "list", tenant_id: "bob" }, { action: "list", actor_id: "bob" }, { action: "admin" }]) assert.equal((await post(request(body))).status, 400);
  const large = new Request("http://local", { method: "POST", body: "a".repeat(8 * 1024 * 1024 + 1) });
  assert.equal((await post(large)).status, 413);
});
test("knowledge binds trusted identity and returns private no-store responses", async () => {
  const original = globalThis.fetch;
  let captured;
  globalThis.fetch = async (_url, options) => { captured = options; return Response.json({ documents: [] }); };
  try {
    const response = await route({ userId: "alice" }, configured)(request({ action: "list" }));
    assert.equal(response.status, 200);
    assert.deepEqual(JSON.parse(captured.body), { actor_id: "alice", tenant_id: "alice", action: "list", payload: {} });
    assert.equal(captured.headers.Authorization, "Bearer local-test-token");
    assert.equal(captured.redirect, "manual");
    assert.equal(response.headers.get("cache-control"), "no-store");
  } finally { globalThis.fetch = original; }
});

test("knowledge refuses upstream redirects without forwarding credentials", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls++;
    assert.equal(options.redirect, "manual");
    return new Response(null, { status: 302, headers: { Location: "https://untrusted.example" } });
  };
  try {
    assert.equal((await route({ userId: "alice" }, configured)(request({ action: "list" }))).status, 503);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});
