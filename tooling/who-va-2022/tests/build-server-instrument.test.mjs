// tooling/who-va-2022/build-server-instrument.mjs emits the committed
// vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json
// artifact: relevant/constraint/calculation source strings for every
// question of the composed instrument, which
// app/services/web_intake_validity_service.py (beads digitva-cal.2 /
// digitva-aiy.1) parses with the existing Python expression parser rather
// than trusting a second AST shape. This pins reproducibility and the one
// cascade (md_available -> md_count -> md_im*) those beads depend on.
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
const generatorPath = path.join(toolingDir, "build-server-instrument.mjs");
const artifactPath = path.join(
  repo,
  "vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json"
);

function regenerate() {
  execFileSync(process.execPath, [generatorPath], { cwd: toolingDir });
}

test("regenerating on an unmodified tree reproduces the committed artifact byte for byte", () => {
  const before = readFileSync(artifactPath, "utf8");
  regenerate();
  const after = readFileSync(artifactPath, "utf8");
  assert.equal(after, before);
});

test("md_available -> md_count -> md_im1 relevance chain is captured, each depending only on its own gate", () => {
  const doc = JSON.parse(readFileSync(artifactPath, "utf8"));
  const byName = Object.fromEntries(doc.questions.map((q) => [q.name, q]));

  assert.equal(byName.md_available.relevant, null);
  assert.equal(byName.md_count.relevant, "selected(${md_available}, 'yes')");
  assert.equal(byName.md_im1.relevant, "${md_count} >= 1");
  assert.equal(byName.md_im1.control, "image");
  assert.equal(byName.md_im1.dataType, "attachment");
});
