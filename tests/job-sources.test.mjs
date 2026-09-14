import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import ts from 'typescript';
import * as wire from '../app/job-sources/tencent-wire.mjs';
import * as zlib from 'node:zlib';
function load(path, imports = {}) {
  const exports = {};
  const compiled = ts.transpileModule(readFileSync(new URL('../' + path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('exports', 'require', compiled)(exports, name => { if (!(name in imports)) throw Error(name); return imports[name]; }); return exports;
}
const importer = load('app/job-sources/importer.ts', { './tencent-wire.mjs': wire });
const url = 'https://docs.qq.com/sheet/DYkp5WkhNS0dPbEZE?tab=5kqpgv';
function fixture() {
  const sqlite = new DatabaseSync(':memory:');
  for (const name of readdirSync(new URL('../drizzle', import.meta.url)).filter(n => n.endsWith('.sql')).sort()) sqlite.exec(readFileSync(new URL('../drizzle/' + name, import.meta.url), 'utf8'));
  const db = { prepare(sql) { let args = []; return { bind(...values) { args = values; return this; }, async first() { return sqlite.prepare(sql).get(...args) || null; }, async all() { return { results: sqlite.prepare(sql).all(...args) }; }, async run() { return sqlite.prepare(sql).run(...args); } }; } };
  let user = { userId:'alice' }, imports = 0;
  const parse = async () => { imports++; return [{id:'job-1',company:'示例',position:'算法'}]; };
  const store = load('app/job-sources/store.ts', { './importer': { ...importer, importSource: parse }, 'node:zlib': zlib });
  const route = load('app/api/job-sources/route.ts', { 'cloudflare:workers': { env: { DB:db } }, '@/app/chatgpt-auth': { getChatGPTUser:async()=>user }, '@/app/job-sources/store':store });
  return { sqlite, db, store, route, user:value=>{user=value;}, imports:()=>imports };
}
const request = (body, origin='http://localhost:5178') => new Request('http://localhost:5178/api/job-sources', {method:'POST',headers:{origin},body:JSON.stringify(body)});
test('source URLs restrict outbound access and retain only sheet selection', () => {
  assert.equal(importer.sourceUrl(url+'&utm=test#frag'),url);
  for (const bad of ['http://docs.qq.com/sheet/a','https://localhost/sheet/a','https://docs.qq.com.evil.test/sheet/a','https://docs.qq.com@evil.test/sheet/a','https://docs.qq.com/dop-api/opendoc']) assert.throws(()=>importer.sourceUrl(bad));
});
test('actual Tencent headers map job details, recruitment type and fallback source link', () => {
  const jobs = importer.jobsFromRows([['汇总'],['','公司类别','公司名称','招聘对象','内推码','投递/内推链接','招聘详情','备注/补充'],['2026.09.11','新能源','示例公司','27届秋招','','','https://example.com/job','算法、研发']], 's','岗位汇总',url);
  assert.equal(jobs.length,1); assert.equal(jobs[0].position,'算法、研发'); assert.equal(jobs[0].link,'https://example.com/job'); assert.deepEqual(jobs[0].recruitmentTypes,['27届秋招']);
  assert.throws(()=>importer.jobsFromRows([['unknown']], 's','name',url));
});
test('document import deduplicates and rejects external endpoints', async () => {
  const row='\u0007示例公司\r\u0007REF\r\u0007\u0013HYPERLINK https://example.com/job\u0014';
  const payload={clientVars:{collab_client_vars:{initialAttributedText:{text:[Buffer.from(row+row).toString('base64')]}}}};
  const jobs=await importer.importSource('id','title','https://docs.qq.com/doc/test',async address=>String(address).includes('opendoc')?new Response('callback('+JSON.stringify(payload)+')'):new Response('<script src="/dop-api/opendoc?id=test"></script>'));
  assert.equal(jobs.length,1); assert.match(jobs[0].id,/^source-/);
  await assert.rejects(importer.importSource('id','title','https://docs.qq.com/doc/test',async()=>new Response('<script src="https://localhost/dop-api/opendoc?id=x"></script>')),/不支持/);
});
test('source API isolates users, blocks forged owners, duplicates and cross-origin writes', async () => {
  const f=fixture(); try {
    const added=await f.route.POST(request({action:'add',name:'测试源',url})); assert.equal(added.status,200);
    const addedBody=await added.json(); const id=addedBody.sources[0].id;
    assert.equal(addedBody.refreshSucceeded,true); assert.deepEqual(addedBody.addedJobs.map(job=>job.id),['job-1']);
    const refreshed=await f.route.POST(request({action:'refresh',id})); assert.equal(refreshed.status,200);
    assert.deepEqual((await refreshed.json()).addedJobs,[]);
    assert.equal((await f.route.POST(request({action:'add',name:'重复',url}))).status,400);
    assert.equal((await f.route.POST(request({action:'remove',id,user_id:'alice'}))).status,400);
    assert.equal((await f.route.POST(request({action:'remove',id},'https://evil.test'))).status,403);
    f.user({userId:'bob'}); assert.deepEqual((await (await f.route.GET()).json()).sources,[]);
    assert.equal((await f.route.POST(request({action:'refresh',id}))).status,404);
    assert.equal((await f.store.sourceFeed(f.db,'bob')).jobs.length,0);
    f.user(null); assert.equal((await f.route.GET()).status,401);
  } finally {f.sqlite.close();}
});
test('failed refresh retains last snapshot; daily schedule skips fresh and paused sources', async () => {
  const f=fixture(); try {
    const id=await f.store.createSource(f.db,'alice','test',url);
    await f.store.refreshDue(f.db); assert.equal(f.imports(),1);
    await f.store.refreshDue(f.db); assert.equal(f.imports(),1);
    const failed=await f.store.refreshSource(f.db,'alice',id,async()=>{throw Error('读取失败');}); assert.equal(failed.succeeded,false);
    assert.equal((await f.store.sourceFeed(f.db,'alice')).jobs.length,1);
    assert.equal((await f.store.listSources(f.db,'alice'))[0].error,'读取失败');
    f.sqlite.prepare('UPDATE radar_sources SET next_run=0,enabled=0').run();
    await f.store.refreshDue(f.db); assert.equal(f.imports(),1);
    f.sqlite.prepare('UPDATE radar_sources SET enabled=1').run();
    await f.store.refreshDue(f.db); assert.equal(f.imports(),2);
  } finally {f.sqlite.close();}
});
test('refresh result contains only jobs added since the previous source snapshot', async () => {
  const f=fixture(); try {
    const id=await f.store.createSource(f.db,'alice','test',url);
    const first=await f.store.refreshSource(f.db,'alice',id,async()=>[
      {id:'job-1',company:'甲公司',position:'算法'},
      {id:'job-2',company:'乙公司',position:'研发'},
    ]);
    assert.deepEqual(first.addedJobs.map(job=>job.id),['job-1','job-2']);
    const second=await f.store.refreshSource(f.db,'alice',id,async()=>[
      {id:'job-2',company:'乙公司',position:'研发'},
      {id:'job-3',company:'丙公司',position:'测试'},
    ]);
    assert.deepEqual(second.addedJobs.map(job=>job.id),['job-3']);
  } finally {f.sqlite.close();}
});
test('refresh lease prevents duplicate work and removal wins over a late response', async () => {
  const f=fixture(); try {
    const id=await f.store.createSource(f.db,'alice','test',url);
    let finish, started; const ready=new Promise(resolve=>{started=resolve});
    const work=f.store.refreshSource(f.db,'alice',id,()=>{started();return new Promise(resolve=>{finish=resolve})});
    await ready; assert.equal(await f.store.refreshSource(f.db,'alice',id),false);
    await f.route.POST(request({action:'remove',id})); finish([{id:'late'}]); await work;
    assert.equal((await f.store.sourceFeed(f.db,'alice')).jobs.length,0);
  } finally {f.sqlite.close();}
});

test('provider redirects are refused without following to another host', async () => {
  let calls = 0;
  await assert.rejects(importer.importSource('id','title',url,async (_address, options) => {
    calls++; assert.equal(options.redirect, 'manual');
    return new Response(null, {status:302, headers:{Location:'http://127.0.0.1/private'}});
  }), /跳转/);
  assert.equal(calls, 1);
});
test('scheduler endpoint requires its server credential', async () => {
  let calls = 0;
  const token = 'test-only-scheduler-token-'.repeat(3);
  const route = load('app/api/job-sources/refresh-due/route.ts', {
    'cloudflare:workers': {env:{DB:{},AGENT_SEARCH_TOKEN:token}},
    '@/app/job-sources/store': {refreshDue:async()=>{calls++;return 1;}},
  });
  assert.equal((await route.POST(new Request('https://app.test/api/job-sources/refresh-due',{method:'POST'}))).status,401);
  assert.equal(calls,0);
  const response = await route.POST(new Request('https://app.test/api/job-sources/refresh-due',{method:'POST',headers:{Authorization:`Bearer ${token}`}}));
  assert.equal(response.status,200); assert.deepEqual(await response.json(),{checked:1}); assert.equal(calls,1);
});
