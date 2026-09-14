import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the GetOffers shell without demo applications", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>GetOffers — 求职进度管理<\/title>/i);
  assert.match(html, /aria-label="主导航"/);
  assert.match(html, /<span class="nav-count">0<\/span>/);
  assert.match(html, /暂无新增岗位/);
  assert.doesNotMatch(html, /完成一次岗位刷新后，新增岗位会显示在这里/);
  assert.doesNotMatch(html, /字节跳动|美团|得物 App/);
});

test("loads jobs from the private sync API instead of a committed snapshot", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /fetch\("\/api\/jobs", \{ cache: "no-store" \}\)/);
  assert.doesNotMatch(page, /job-feed\.json/);

  await assert.rejects(
    access(new URL("../public/job-feed.json", import.meta.url)),
    /ENOENT/,
  );
});

test("protects job publishing and private reads at the API boundary", async () => {
  const route = await readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8");
  assert.match(route, /JOB_FEED_SYNC_SECRET/);
  assert.match(route, /authorization\.startsWith\("Bearer "\)/);
  assert.match(route, /getChatGPTUser\(\)/);
  assert.match(route, /JOB_FEEDS\.put/);
  assert.match(route, /JOB_FEEDS\.get/);
  assert.match(route, /MAX_FEED_BYTES/);
  assert.match(route, /cleanHttpUrl/);
});
