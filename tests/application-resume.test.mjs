import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import ts from 'typescript';
import { drizzle } from 'drizzle-orm/d1';

const require = createRequire(import.meta.url);
function load(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL('../' + path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  new Function('require', 'exports', compiled)((name) => imports[name] ?? require(name), exports);
  return exports;
}
const schema = load('db/schema.ts');
const files = load('app/knowledge/files.ts');
const resume = load('app/api/applications/resume-reference.ts', {
  'cloudflare:workers': { env: { AGENT_KNOWLEDGE_URL: 'http://127.0.0.1:8767', AGENT_KNOWLEDGE_TOKEN: 'test-secret' } },
  '@/app/knowledge/files': files,
});
function fixture() {
  const sqlite = new DatabaseSync(':memory:');
  const migrations = readdirSync(new URL('../drizzle/', import.meta.url)).filter((p) => p.endsWith('.sql')).sort();
  for (const file of migrations) sqlite.exec(readFileSync(new URL('../drizzle/' + file, import.meta.url), 'utf8'));
  const binding = { prepare(sql) {
    let args = [];
    return { bind(...values) { args = values; return this; },
      async raw() { return sqlite.prepare(sql).all(...args).map((row) => Object.values(row)); },
      async all() { return { results: sqlite.prepare(sql).all(...args) }; },
      async run() { return { meta: sqlite.prepare(sql).run(...args) }; },
    };
  }};
  const db = drizzle(binding, { schema });
  const api = (userId) => load('app/api/applications/route.ts', {
    '@/app/chatgpt-auth': { getChatGPTUser: async () => userId ? { userId, displayName: userId, email: '' } : null },
    '@/db': { getDb: () => db }, '@/db/schema': schema, './resume-reference': resume,
  });
  return { sqlite, api };
}
function request(body) { return new Request('http://local/api/applications', { method: 'POST', body: JSON.stringify(body) }); }
const base = { id: 'record', company: '合成公司', role: '算法工程师', status: 'pending', resume: 'legacy' };
const document = { document_id: 'doc', name: '简历.pdf', status: 'active', versions: [
  { version_id: 'v2', extension: 'pdf', created_at: '2026-09-06' },
  { version_id: 'v1', extension: 'pdf', created_at: '2026-09-05' },
] };

test('migration preserves old resume labels and gives them empty file references', () => {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('../drizzle/0000_oval_bishop.sql', import.meta.url), 'utf8'));
  sqlite.exec("INSERT INTO applications(user_id,id,company,role,status,resume,created_at,updated_at) VALUES('alice','old','company','role','pending','旧版简历','today','today')");
  sqlite.exec(readFileSync(new URL('../drizzle/0003_talented_toxin.sql', import.meta.url), 'utf8'));
  const row = sqlite.prepare('SELECT resume,resume_document_id,resume_version_id FROM applications').get();
  assert.equal(row.resume, '旧版简历');
  assert.equal(row.resume_document_id, '');
  assert.equal(row.resume_version_id, '');
  sqlite.close();
});

test('application persists an exact owned file version and returns a canonical label', async () => {
  const f = fixture(); const original = globalThis.fetch; let sent;
  globalThis.fetch = async (_url, options) => { sent = JSON.parse(options.body); assert.equal(options.redirect, 'manual'); return Response.json({ documents: sent.tenant_id === 'alice' ? [document] : [] }); };
  try {
    const response = await f.api('alice').POST(request({ ...base, resume: 'forged label', resumeDocumentId: 'doc', resumeVersionId: 'v1' }));
    assert.equal(response.status, 200);
    const saved = (await response.json()).application;
    assert.equal(saved.resume, '简历.pdf · 版本 1');
    assert.equal(saved.resumeVersionId, 'v1');
    assert.equal(saved.resumeDocumentId, 'doc');
    assert.deepEqual(sent, { actor_id: 'alice', tenant_id: 'alice', action: 'list', payload: {} });
    const read = await f.api('alice').GET();
    assert.equal((await read.json()).applications[0].resumeVersionId, 'v1');
    assert.deepEqual((await (await f.api('bob').GET()).json()).applications, []);
    assert.equal((await f.api('bob').POST(request(saved))).status, 400);
    globalThis.fetch = async () => { throw new Error('must not need current files'); };
    const changed = await f.api('alice').POST(request({ ...saved, status: 'applied', resume: 'overwrite history' }));
    assert.equal(changed.status, 200);
    assert.equal((await changed.json()).application.resume, '简历.pdf · 版本 1');
  } finally { globalThis.fetch = original; f.sqlite.close(); }
});

test('foreign, mismatched, partial and deleting references fail before any import writes', async () => {
  const f = fixture(); const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ documents: [document, { ...document, document_id: 'deleting', status: 'deleting' }] });
  try {
    for (const refs of [
      { resumeDocumentId: 'foreign', resumeVersionId: 'v1' },
      { resumeDocumentId: 'doc', resumeVersionId: 'wrong' },
      { resumeDocumentId: 'doc' },
      { resumeDocumentId: 42, resumeVersionId: 'v1' },
      { resumeDocumentId: 'deleting', resumeVersionId: 'v1' },
    ]) {
      const response = await f.api('alice').POST(request({ ...base, ...refs }));
      assert.equal(response.status, 400);
      assert.equal((await response.json()).error, 'INVALID_RESUME_REFERENCE');
    }
    const response = await f.api('alice').PUT(request({ applications: [base, { ...base, id: 'invalid', resumeDocumentId: 'foreign', resumeVersionId: 'v1' }] }));
    assert.equal(response.status, 400);
    assert.equal(f.sqlite.prepare('SELECT COUNT(*) AS n FROM applications').get().n, 0);
  } finally { globalThis.fetch = original; f.sqlite.close(); }
});

test('legacy labels and explicit unlink work without the knowledge service', async () => {
  const f = fixture(); const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('no request expected'); };
  try {
    const saved = await f.api('alice').POST(request(base));
    assert.equal(saved.status, 200);
    assert.equal((await saved.json()).application.resumeDocumentId, '');
    const imported = await f.api('alice').PUT(request({ applications: [{ ...base, id: 'imported', resume: '旧版简历' }] }));
    assert.equal(imported.status, 200);
    f.sqlite.exec("UPDATE applications SET resume_document_id='doc',resume_version_id='v1' WHERE id='record'");
    const clear = await f.api('alice').POST(request({ ...base, resume: '', resumeDocumentId: '', resumeVersionId: '' }));
    assert.equal((await clear.json()).application.resume, '');
  } finally { globalThis.fetch = original; f.sqlite.close(); }
});
