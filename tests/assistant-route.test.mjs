import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import * as React from "react";
import * as jsx from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";

function load(path, imports) {
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL("../" + path, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  new Function("require", "exports", source)((name) => { if (!(name in imports)) throw Error(name); return imports[name]; }, exports);
  return exports;
}
const configured = { AGENT_ASSISTANT_URL: "http://localhost:8780", AGENT_ASSISTANT_TOKEN: "synthetic-test-token-".repeat(3) };
const route = (user = { userId: "alice" }, env = configured) => load("app/api/assistant/route.ts", { "cloudflare:workers": { env }, "@/app/chatgpt-auth": { getChatGPTUser: async () => user } });
const request = (body) => new Request("https://local/api/assistant", { method: "POST", body: JSON.stringify(body) });
const payload = { request_id: "test-request", messages: [{ role: "user", content: "帮我梳理项目" }], materials: [], jd: "" };

test("assistant requires login and configured service; rejects identity injection and oversized input", async () => {
  assert.equal((await route(null).GET()).status, 401);
  assert.equal((await route(null).POST(request(payload))).status, 401);
  assert.deepEqual(await (await route(undefined, {}).GET()).json(), { configured: false });
  assert.equal((await route(undefined, {}).POST(request(payload))).status, 503);
  assert.equal((await route().POST(request({ ...payload, actor_id: "bob" }))).status, 400);
  assert.equal((await route().POST(request({ ...payload, messages: ["x".repeat(380000)] }))).status, 413);
});

test("assistant binds identity and forwards progress before upstream completion", async () => {
  const original = globalThis.fetch;
  let stream;
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url.pathname, "/assistant"); assert.equal(options.redirect, "manual");
      assert.equal(options.headers.Authorization, "Bearer " + configured.AGENT_ASSISTANT_TOKEN);
      assert.deepEqual(JSON.parse(options.body), { actor_id: "alice", tenant_id: "alice", payload });
      return new Response(new ReadableStream({ start(controller) { stream = controller; controller.enqueue(new TextEncoder().encode('{"type":"progress","label":"查找相关材料"}\n')); } }), { headers: { "Content-Type": "application/x-ndjson" } });
    };
    const result = await route().POST(request(payload));
    assert.equal(result.status, 200); assert.equal(result.headers.get("cache-control"), "no-store");
    const reader = result.body.getReader();
    assert.match(new TextDecoder().decode((await reader.read()).value), /查找相关材料/);
    stream.enqueue(new TextEncoder().encode('{"type":"done"}\n')); stream.close();
    assert.match(new TextDecoder().decode((await reader.read()).value), /done/);
    assert.equal((await reader.read()).done, true);
  } finally { globalThis.fetch = original; }
});

test("assistant rejects redirects and wrong upstream protocol without relaying provider errors", async () => {
  const original = globalThis.fetch;
  try {
    for (const response of [new Response(null, { status: 302 }), Response.json({ error: "private detail" })]) {
      globalThis.fetch = async () => response;
      const result = await route().POST(request(payload));
      assert.equal(result.status, 503);
      assert.deepEqual(await result.json(), { error: "ASSISTANT_UNAVAILABLE" });
    }
    globalThis.fetch = async () => Response.json({ configured: true, secret: "hidden" });
    assert.deepEqual(await (await route().GET()).json(), { configured: true });
  } finally { globalThis.fetch = original; }
});

test("assistant Markdown keeps model HTML and unsafe links as inert text", () => {
  const Markdown = load("app/assistant/markdown.tsx", { react: React, "react/jsx-runtime": jsx }).default;
  const html = renderToStaticMarkup(React.createElement(Markdown, { text: '# 草稿\n**重点**\n<img src=x onerror=alert(1)>\n[危险链接](javascript:alert(1))\n- 项目\n1. 问题\n```\n<script>bad()</script>\n```' }));
  assert.match(html, /<strong>重点<\/strong>/);
  assert.match(html, /<ul>/); assert.match(html, /<ol>/);
  assert.doesNotMatch(html, /<img|<script|<a /);
  assert.match(html, /&lt;img/);
});
