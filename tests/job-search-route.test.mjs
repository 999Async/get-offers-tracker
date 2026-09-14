import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = fs.readFileSync(new URL("../app/api/job-search/route.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;

function route(user, env = {}) {
  const exports = {};
  const require = (name) => name === "cloudflare:workers" ? { env } : {
    getChatGPTUser: async () => user,
  };
  new Function("require", "exports", compiled)(require, exports);
  return exports.POST;
}

function request(body) {
  return new Request("https://getoffers.example/api/job-search", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

test("unauthenticated and unconfigured product calls fail closed", async () => {
  assert.equal((await route(null)(request({ query: "Agent" }))).status, 401);
  assert.equal((await route({ userId: "alice" })(request({ query: "Agent" }))).status, 503);
});

test("browser cannot inject a tenant or storage filter", async () => {
  const post = route({ userId: "alice" }, { AGENT_SEARCH_URL: "http://127.0.0.1:8766",
    AGENT_SEARCH_TOKEN: "secret" });
  for (const extra of [{ tenant_id: "bob" }, { actor_id: "bob" }, { query_filter: {} }]) {
    assert.equal((await post(request({ query: "Agent", ...extra }))).status, 400);
  }
});

test("product binds identity and does not forward browser authorization", async () => {
  const original = globalThis.fetch;
  let captured;
  globalThis.fetch = async (_url, options) => {
    captured = options;
    return Response.json({ jobs: [] });
  };
  try {
    const post = route({ userId: "alice" }, { AGENT_SEARCH_URL: "https://agent.example",
      AGENT_SEARCH_TOKEN: "server-secret" });
    const result = await post(request({ query: "Agent", top_k: 5 }));
    assert.equal(result.status, 200);
    assert.deepEqual(JSON.parse(captured.body), { actor_id: "alice", tenant_id: "alice",
      request: { query: "Agent", top_k: 5 } });
    assert.equal(captured.headers.Authorization, "Bearer server-secret");
    assert.equal(captured.redirect, "error");
    assert.equal(result.headers.get("cache-control"), "no-store");
  } finally { globalThis.fetch = original; }
});
