// tooling/who-va-2022/build.mjs emits the committed browser bundle
// app/static/vendor/who-va-2022/who-va-2022.web-component.js plus its
// manifest.json. This pins the invariant that makes "is the committed
// bundle current?" answerable by comparison: rebuilding on an unmodified
// tree must reproduce both files byte for byte. Before digitva-cw9, the
// manifest carried a `built_at` timestamp, so every rebuild dirtied it even
// when the bundle itself was unchanged -- and that noise is what let the
// bundle committed in 926c212 diverge from its own source unnoticed until a
// manual check caught it (fixed in 7bf1d5f).
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const toolingDir = path.resolve(here, "..");
const repo = path.resolve(toolingDir, "..", "..");
const buildScript = path.join(toolingDir, "build.mjs");
const bundleDir = path.join(repo, "app/static/vendor/who-va-2022");
const bundlePath = path.join(bundleDir, "who-va-2022.web-component.js");
const manifestPath = path.join(bundleDir, "manifest.json");

function rebuild() {
  execFileSync(process.execPath, [buildScript], { cwd: toolingDir });
}

test("rebuilding on an unmodified tree reproduces the committed bundle byte for byte", () => {
  const before = readFileSync(bundlePath);
  rebuild();
  const after = readFileSync(bundlePath);
  assert.ok(before.equals(after));
});

test("rebuilding on an unmodified tree reproduces the committed manifest byte for byte", () => {
  const before = readFileSync(manifestPath, "utf8");
  rebuild();
  const after = readFileSync(manifestPath, "utf8");
  assert.equal(after, before);
});

test("manifest carries no timestamp-shaped field", () => {
  const raw = readFileSync(manifestPath, "utf8");
  assert.equal(raw.includes("built_at"), false);
  assert.equal(raw.includes("builtAt"), false);
});

test("manifest's bytes and sha256 match the committed bundle file", () => {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const bundle = readFileSync(bundlePath);
  assert.equal(manifest.bytes, bundle.length);
  assert.equal(manifest.file, "who-va-2022.web-component.js");
});
