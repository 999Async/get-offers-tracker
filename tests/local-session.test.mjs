import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
const code = ts.transpileModule(readFileSync(new URL('../app/assistant/local-session.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function load(responses) {
  const calls = [], events = [], exports = {};
  new Function('exports', 'fetch', 'window', code)(exports, async (_url, options) => {
    calls.push(options);
    const response = responses.shift();
    assert.ok(response, 'unexpected network call');
    return response;
  }, { dispatchEvent: event => events.push(event.detail) });
  return { ...exports, calls, events };
}
test('concurrent initial loads connect once, then announce the verified session', async () => {
  const connected = { local: true, connected: true, model: 'model-a' };
  const api = load([Response.json({ local: true, connected: false }), Response.json({ connected: true }), Response.json(connected)]);
  const [first, second] = await Promise.all([api.ensureLocalConnection(), api.ensureLocalConnection()]);
  assert.deepEqual(first, connected); assert.deepEqual(second, connected);
  assert.equal(api.calls.length, 3);
  assert.deepEqual(JSON.parse(api.calls[1].body), { action: 'connect' });
  assert.deepEqual(api.events, [{ action: 'connect' }]);
});
test('existing session and hosted mode never send connect requests', async () => {
  for (const response of [Response.json({ local: true, connected: true }), new Response(null, { status: 404 })]) {
    const api = load([response]); await api.ensureLocalConnection();
    assert.equal(api.calls.length, 1); assert.equal(api.events.length, 0);
  }
});
test('failed connection stays unauthenticated and can be retried', async () => {
  const api = load([Response.json({ local: true, connected: false }), new Response(null, { status: 503 }), Response.json({ local: true, connected: false }), Response.json({ connected: true }), Response.json({ local: true, connected: true })]);
  await assert.rejects(api.ensureLocalConnection(), /CLI/);
  assert.equal(api.events.length, 0);
  assert.equal((await api.ensureLocalConnection()).connected, true);
  assert.equal(api.events.length, 1);
});
test('a connect response alone does not establish an authenticated session', async () => {
  const api = load([Response.json({ local: true, connected: false }), Response.json({ connected: true }), Response.json({ local: true, connected: false })]);
  await assert.rejects(api.ensureLocalConnection(), /连接未完成/);
  assert.equal(api.events.length, 0);
});
