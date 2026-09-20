// tooling/who-va-2022/build-expression-corpus.mjs emits the committed
// vendor/who-va-2022/src/generated/expression-conformance-corpus.json
// artifact: golden results from the real TypeScript expression engine that
// app/services/xform_expression_evaluator.py's Python port is graded
// against. This pins the invariant that makes the artifact trustworthy
// (regenerating it reproduces the same file) plus a few properties of the
// fixture design itself (beads digitva-cal.1).
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { collectReferences } from "../build-expression-corpus.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const toolingDir = path.resolve(here, "..");
const repo = path.resolve(toolingDir, "..", "..");
const generatorPath = path.join(toolingDir, "build-expression-corpus.mjs");
const artifactPath = path.join(
  repo,
  "vendor/who-va-2022/src/generated/expression-conformance-corpus.json"
);

function regenerate() {
  execFileSync(process.execPath, [generatorPath], { cwd: toolingDir });
}

function readArtifact() {
  return JSON.parse(readFileSync(artifactPath, "utf8"));
}

test("regenerating on an unmodified tree reproduces the committed artifact byte for byte", () => {
  const before = readFileSync(artifactPath, "utf8");
  regenerate();
  const after = readFileSync(artifactPath, "utf8");
  assert.equal(after, before);
});

test("carries no timestamp-shaped field", () => {
  const raw = readFileSync(artifactPath, "utf8");
  assert.equal(raw.includes("built_at"), false);
  assert.equal(raw.includes("builtAt"), false);
});

test("every unique expression in the composed instrument parses (no unsupported function slipped in)", () => {
  const doc = readArtifact();
  for (const entry of doc.entries) {
    assert.equal(entry.parseError, null, `expected ${JSON.stringify(entry.source)} to parse`);
  }
});

test("covers both branches of a boolean expression -- not only-ever-false", () => {
  const doc = readArtifact();
  const results = doc.entries.flatMap((entry) => entry.cases.map((c) => c.result));
  assert.ok(results.includes(true), "no case in the whole corpus evaluated to true");
  assert.ok(results.includes(false), "no case in the whole corpus evaluated to false");
});

test("the Devanagari-digit divergence trap (sa13-sa19's regex) is represented and reads false under the JS engine", () => {
  const doc = readArtifact();
  const entry = doc.entries.find((e) => e.source.includes("\\d"));
  assert.ok(entry, "no regex(...,'...\\d...') expression found in the composed instrument");
  const digitCase = entry.cases.find((c) => /[०-९]/.test(c.currentValue ?? ""));
  assert.ok(digitCase, "no case exercises a Devanagari-digit answer");
  assert.equal(digitCase.result, false, "JavaScript's \\d is ASCII-only and must read this as no match");
  // And the corpus is not vacuous about this pattern: an ASCII digit case
  // exists too, and it reads true.
  assert.ok(entry.cases.some((c) => c.result === true), "no ASCII-digit case for this pattern reads true");
});

test("collectReferences finds every ${...} reference and whether '.' is read", () => {
  const ast = {
    type: "binary",
    operator: "and",
    left: { type: "call", name: "selected", arguments: [{ type: "reference", name: "a" }, { type: "literal", value: "x" }] },
    right: { type: "binary", operator: ">", left: { type: "current" }, right: { type: "reference", name: "b" } }
  };
  const { names, usesCurrent } = collectReferences(ast);
  assert.deepEqual([...names].sort(), ["a", "b"]);
  assert.equal(usesCurrent, true);

  const noCurrent = collectReferences({ type: "literal", value: 1 });
  assert.equal(noCurrent.usesCurrent, false);
  assert.equal(noCurrent.names.size, 0);
});
