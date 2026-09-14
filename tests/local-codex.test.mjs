import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Readable } from 'node:stream';
import test from 'node:test';
import ts from 'typescript';
const exports = {};
new Function('exports', ts.transpileModule(readFileSync(new URL('../build/local-codex.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText)(exports);

async function exercise({ method = 'GET', host = 'localhost:5178', origin, cookie, body, path = '/api/applications', developer = false, upstream = {} } = {}) {
  let middleware;
  process.env.GETOFFERS_LOCAL_DEVELOPER = developer ? '1' : '0';
  process.env.GETOFFERS_LOCAL_CODEX = '1'; process.env.AGENT_ASSISTANT_TOKEN = 'x'.repeat(32);
  exports.localCodex().configureServer({ config: { server: { port: 5178 } }, httpServer: { address: () => ({ port: 5178 }) }, middlewares: { use: fn => { middleware = fn; } } });
  const req = Readable.from(body ? [JSON.stringify(body)] : []);
  Object.assign(req, { url: path, method, headers: { host, origin, cookie, 'oai-authenticated-user-id': 'forged' }, socket: { remoteAddress: "127.0.0.1" }, rawHeaders: ['Host', host, 'Oai-Authenticated-User-Id', 'forged'] });
  let status = 0, output = '', next = false; const headers = {};
  const res = { setHeader: (k, v) => { headers[k] = v; }, writeHead: (code, h) => { status = code; Object.assign(headers, h); }, end: value => { output = value || ''; } };
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, options) => { const request = JSON.parse(options.body); return Response.json(typeof upstream === 'function' ? upstream(request) : upstream); };
  try { await middleware(req, res, () => { next = true; }); }
  finally { globalThis.fetch = original; delete process.env.GETOFFERS_LOCAL_CODEX; delete process.env.GETOFFERS_LOCAL_DEVELOPER; delete process.env.AGENT_ASSISTANT_TOKEN; }
  return { req, status, output, headers, next };
}

test('dev identity is stripped from both normalized and raw headers', async () => {
  const result = await exercise();
  assert.equal(result.next, true);
  assert.equal(result.req.headers['oai-authenticated-user-id'], undefined);
  assert.deepEqual(result.req.rawHeaders, ['Host', 'localhost:5178']);
});
test('valid cookie resolves server identity into the worker request', async () => {
  const result = await exercise({ cookie: 'getoffers_local=real-session', upstream: input => {
    assert.equal(input.session, 'real-session'); return { userId: 'verified', email: 'verified@example.com' };
  } });
  assert.equal(result.req.headers['oai-authenticated-user-id'], 'verified');
  assert.ok(result.req.rawHeaders.includes('verified'));
  assert.ok(!result.req.rawHeaders.includes('forged'));
});
test('rejects foreign host, cross-site and missing-origin mutations', async () => {
  assert.equal((await exercise({ host: 'attacker.test:5178' })).status, 403);
  assert.equal((await exercise({ method: 'POST', origin: 'https://attacker.test' })).status, 403);
  assert.equal((await exercise({ method: 'POST' })).status, 403);
});
test('connect issues an HttpOnly cookie without exposing session in JSON', async () => {
  const result = await exercise({ path: '/api/local-assistant', method: 'POST', origin: 'http://localhost:5178', body: { action: 'connect' }, upstream: { session: 'secret-session', connected: true } });
  assert.equal(result.status, 200);
  assert.match(result.headers['Set-Cookie'], /HttpOnly; SameSite=Strict/);
  assert.deepEqual(JSON.parse(result.output), { connected: true });
});
test('browser cannot claim identity or pass arbitrary local command', async () => {
  const result = await exercise({ path: '/api/local-assistant', method: 'POST', origin: 'http://localhost:5178', body: { action: 'connect', email: 'forged@example.com' } });
  assert.equal(result.status, 400);
});


test('developer gateway requires opt-in and cookie; rejects client identity or file paths', async () => {
  const path = '/api/developer-observability?action=capabilities';
  assert.equal((await exercise({ path, cookie:'getoffers_local=real' })).status, 404);
  assert.equal((await exercise({ path, developer:true })).status, 403);
  assert.equal((await exercise({ path:path+'&session=forged', developer:true, cookie:'getoffers_local=real' })).status, 400);
  assert.equal((await exercise({ path:path+'&path=/private/file', developer:true, cookie:'getoffers_local=real' })).status, 400);
  const allowed = await exercise({ path, developer:true, cookie:'getoffers_local=real', upstream: body => {
    assert.equal(body.session, 'real'); assert.equal(body.action, 'capabilities');
    assert.deepEqual(Object.keys(body).sort(), ['action','session']);
    return { capabilities:['metrics:read'] };
  } });
  assert.equal(allowed.status, 200);
  assert.equal(allowed.headers['Cache-Control'], 'no-store');
  assert.equal((await exercise({ path, developer:true, cookie:'getoffers_local=real', method:'POST', origin:'http://localhost:5178' })).status, 405);
});
