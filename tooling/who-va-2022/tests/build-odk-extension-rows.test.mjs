// tooling/who-va-2022/build-odk-extension-rows.mjs emits the extension row
// specs consumed by app/services/xlsform_service.py.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const toolingDir = path.resolve(here, "..");
const repo = path.resolve(toolingDir, "..", "..");
const generatorPath = path.join(toolingDir, "build-odk-extension-rows.mjs");
const artifactPath = path.join(repo, "resource", "xlsform_extensions", "digitva_core.json");
const webArtifactPath = path.join(repo, "app", "data", "who-va-2022.composed.json");

test("regenerating reproduces the extension specs byte for byte", () => {
  const before = readFileSync(artifactPath, "utf8");
  execFileSync(process.execPath, [generatorPath], { cwd: toolingDir });
  assert.equal(readFileSync(artifactPath, "utf8"), before);
});
test("typed narrative changes are copied from the composed web definition", () => {
  const spec = JSON.parse(readFileSync(artifactPath, "utf8"));
  const web = JSON.parse(readFileSync(webArtifactPath, "utf8"));
  const webQuestions = Object.fromEntries(web.questions.map((question) => [question.name, question]));
  const block = spec.blocks.find((item) => item.id === "core_typed_narrative_visibility");
  assert.ok(block);
  assert.deepEqual(block.survey, []);
  assert.deepEqual(
    Object.fromEntries(block.change.map((change) => [change.name, change.cells])),
    {
      Id10476: { relevant: webQuestions.Id10476.relevant?.source ?? null },
      Id10476_audio: { hint: webQuestions.Id10476_audio.hint?.en ?? null },
    },
  );
  assert.equal(webQuestions.Id10476.required, true);
  assert.equal(webQuestions.Id10476.appearance, "multiline");
  assert.equal(webQuestions.Id10476.validation.required, true);
});
