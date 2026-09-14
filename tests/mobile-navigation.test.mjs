import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("mobile navigation exposes every primary destination", async () => {
  const [page, css] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
  ]);

  assert.doesNotMatch(page, /navItems\.slice\(0,\s*4\)/);
  assert.match(page, /<nav className="mobile-nav"[^>]*>[\s\S]*?\{navItems\.map\(/);
  assert.match(
    css,
    /\.mobile-nav\s*\{[^}]*grid-template-columns:\s*repeat\(7,\s*1fr\)/s,
  );
});
