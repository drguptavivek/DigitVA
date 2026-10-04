// tooling/who-va-2022/build-composed-instrument.mjs emits
// app/data/who-va-2022.composed.json, which app/services/served_form_service.py
// filters per project. The generator itself fails unless filter(tagged, S)
// equals compose(always-on + S) for all 32 extension subsets; this pins that it
// still runs clean, reproduces the committed file byte for byte, and writes the
// version/engineVersion the endpoint serves.
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
const generatorPath = path.join(toolingDir, "build-composed-instrument.mjs");
const artifactPath = path.join(repo, "app/data/who-va-2022.composed.json");

test("regenerating reproduces the committed file byte for byte and passes the 32-subset check", () => {
  const before = readFileSync(artifactPath, "utf8");
  const output = execFileSync(process.execPath, [generatorPath], { cwd: toolingDir, encoding: "utf8" });
  assert.match(output, /Subset check: 32\/32 subsets match/);
  assert.equal(readFileSync(artifactPath, "utf8"), before);
});

test("the file carries a composed version, the engine version and the tags", () => {
  const doc = JSON.parse(readFileSync(artifactPath, "utf8"));
  assert.match(doc.version, /^\d+-[0-9a-f]{10}$/);
  assert.equal(doc.engineVersion, 1);
  const tagged = (kind) => doc[kind].filter((item) => item.extensions);
  assert.ok(tagged("questions").length > 0 && tagged("sections").length > 0);
  const documents = doc.sections.find((section) => section.name === "digitva_documents");
  assert.deepEqual(documents.extensions, ["death_summary", "medical_records"]);
});
