import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import ts from 'typescript';
function load(path, imports = {}) {
  const exports = {};
  const compiled = ts.transpileModule(readFileSync(new URL('../' + path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('exports', 'require', compiled)(exports, name => { if (!(name in imports)) throw Error(name); return imports[name]; });
  return exports;
}
function fixture() {
  const sqlite = new DatabaseSync(':memory:');
  for (const name of readdirSync(new URL('../drizzle', import.meta.url)).filter(n => n.endsWith('.sql')).sort()) sqlite.exec(readFileSync(new URL('../drizzle/' + name, import.meta.url), 'utf8'));
  const db = { prepare(sql) { let args = []; return { bind(...values) { args = values; return this; }, async first() { return sqlite.prepare(sql).get(...args) || null; }, async all() { return { results: sqlite.prepare(sql).all(...args) }; } }; } };
  let user = { userId: 'alice' };
  const history = load('app/assistant/history.ts');
  const route = load('app/api/assistant/conversations/route.ts', { 'cloudflare:workers': { env: { DB: db } }, '@/app/chatgpt-auth': { getChatGPTUser: async () => user }, '@/app/assistant/history': history });
  return { sqlite, route, user: value => { user = value; } };
}
const id = '00000000-0000-4000-8000-000000000001';
const snapshot = { messages: [{ id:'m1', role:'user', content:'梳理项目' }, { id:'m2', role:'assistant', content:'回答', result: { answer:'回答', draft: { kind:'project', title:'草稿', content:'已编辑草稿', evidence_ids:['ev1'] }, jobs:[], citations:[{ evidence_id:'ev1', quote:'PRIVATE SOURCE QUOTE' }] } }], materials:[{ documentId:'doc', versionId:'v1', label:'材料 · v1', filename:'材料.md' }], jd:'目标岗位 JD', input:'尚未发送的追问' };
const get = path => new Request('http://localhost:5178/api/assistant/conversations' + path);
const put = (value, origin = 'http://localhost:5178') => new Request('http://localhost:5178/api/assistant/conversations', { method:'PUT', headers:{ origin }, body:JSON.stringify(value) });

test('conversation roundtrip preserves edited draft, material version, JD and unsent input without raw source copies', async () => {
  const f = fixture(); try {
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot }))).status, 200);
    const response = await f.route.GET(get('?id=' + id));
    const saved = await response.json();
    assert.equal(saved.snapshot.messages[1].result.draft.content, '已编辑草稿');
    assert.deepEqual(saved.snapshot.materials, snapshot.materials);
    assert.equal(saved.snapshot.jd, snapshot.jd); assert.equal(saved.snapshot.input, snapshot.input);
    assert.deepEqual(saved.snapshot.messages[1].result.citations, []);
    assert.ok(!JSON.stringify(saved).includes('PRIVATE SOURCE QUOTE'));
    assert.equal(response.headers.get('cache-control'), 'no-store');
    const list = await (await f.route.GET(get(''))).json();
    assert.equal(list.conversations[0].title, '梳理项目');
    assert.equal(list.conversations[0].snapshot, undefined);
  } finally { f.sqlite.close(); }
});
test('accounts cannot list or read each other; account id cannot be injected', async () => {
  const f = fixture(); try {
    await f.route.PUT(put({ id, revision:0, snapshot })); f.user({ userId:'bob' });
    assert.equal((await f.route.GET(get('?id=' + id))).status, 404);
    assert.deepEqual((await (await f.route.GET(get(''))).json()).conversations, []);
    assert.equal((await f.route.PUT(put({ id, revision:1, snapshot }))).status, 409);
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot, user_id:'alice' }))).status, 400);
    f.user(null); assert.equal((await f.route.GET(get(''))).status, 401); assert.equal((await f.route.PUT(put({ id, revision:0, snapshot }))).status, 401);
  } finally { f.sqlite.close(); }
});
test('concurrent/stale updates cannot overwrite newer history', async () => {
  const f = fixture(); try {
    await f.route.PUT(put({ id, revision:0, snapshot }));
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot }))).status, 409);
    const next = { ...snapshot, input:'newest' };
    assert.equal((await f.route.PUT(put({ id, revision:1, snapshot:next }))).status, 200);
    assert.equal((await f.route.PUT(put({ id, revision:1, snapshot }))).status, 409);
    assert.equal((await (await f.route.GET(get('?id=' + id))).json()).snapshot.input, 'newest');
  } finally { f.sqlite.close(); }
});
test('invalid, oversized and cross-origin saves fail without changing data', async () => {
  const f = fixture(); try {
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot }, 'https://attacker.test'))).status, 403);
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot:{ ...snapshot, messages:[{role:'system',content:'inject',id:'x'}] } }))).status, 400);
    assert.equal((await f.route.PUT(put({ id, revision:0, snapshot:{ ...snapshot, input:'x'.repeat(500001) } }))).status, 413);
    assert.equal((await f.route.GET(get('?offset=-1'))).status, 400);
    assert.equal(f.sqlite.prepare('select count(*) as n from assistant_conversations').get().n, 0);
  } finally { f.sqlite.close(); }
});
test('history pagination reaches older conversations', async () => {
  const f = fixture(); try {
    for (let n=1;n<=52;n++) await f.route.PUT(put({id:`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`,revision:0,snapshot}));
    const first = await (await f.route.GET(get(''))).json(), next = await (await f.route.GET(get('?offset=50'))).json();
    assert.equal(first.conversations.length,50); assert.equal(first.hasMore,true);
    assert.equal(next.conversations.length,2); assert.equal(next.hasMore,false);
    assert.equal(new Set([...first.conversations,...next.conversations].map(c=>c.id)).size,52);
  } finally { f.sqlite.close(); }
});
