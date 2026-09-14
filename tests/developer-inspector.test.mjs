import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
const exports = {};
new Function('exports', ts.transpileModule(readFileSync(new URL('../app/developer/format.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText)(exports);
test('developer costs distinguish unknown, zero and small positive provider costs', () => {
  assert.equal(exports.formatCost(null), '未知');
  assert.equal(exports.formatCost(undefined), '未知');
  assert.equal(exports.formatCost(0), '0');
  assert.equal(exports.formatCost(0.001), '0.001');
  assert.equal(exports.formatCost(0.0000001), '<0.000001');
  assert.equal(exports.formatCost(Number.NaN), '未知');
});
