// tooling/who-va-2022/build-layer-reference.mjs emits the committed
// vendor/who-va-2022/src/generated/digitva-layers.reference.json artifact:
// the DigitVA-only questions/sections/choices Python's
// instrument_translation_service has no other way to learn about. This
// pins the invariants that make that artifact trustworthy rather than a
// second, driftable copy of digitva-extension.ts (beads digitva-cw9 is what
// an undetected drift looks like in this codebase).
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { assertChoiceLabelMatchesBase, assertNoDot, stableStringify } from "../build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const toolingDir = path.resolve(here, "..");
const repo = path.resolve(toolingDir, "..", "..");
const generatorPath = path.join(toolingDir, "build-layer-reference.mjs");
const artifactPath = path.join(
  repo,
  "vendor/who-va-2022/src/generated/digitva-layers.reference.json"
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

test("does not touch the browser bundle output directory", () => {
  // The generator emits a data file only; app/static/vendor/who-va-2022 is
  // the committed esbuild bundle and must stay byte-identical.
  regenerate();
  const status = execFileSync(
    "git",
    ["status", "--porcelain", "--", "app/static/vendor/who-va-2022/"],
    { cwd: repo, encoding: "utf8" }
  );
  assert.equal(status.trim(), "");
});

test("every DigitVA extension that contributes questions is represented", () => {
  const doc = readArtifact();
  const { extensionCounts } = doc;

  // These four gate the question groups digitva-extension.ts emits, plus
  // digitva_core's always-on splice: all must contribute at least one item.
  for (const extension of ["digitva_core", "narration_language", "death_summary", "medical_records", "abha"]) {
    assert.ok(extensionCounts[extension], `missing extensionCounts entry for ${extension}`);
    const total = extensionCounts[extension].questions + extensionCounts[extension].sections + extensionCounts[extension].choices;
    assert.ok(total > 0, `${extension} contributed no entries`);
  }

  // social_autopsy, intake_screen and geography gate content outside this
  // module (digitva-extension.ts's own header comment) and so contribute
  // nothing to this artifact -- present as a key, with a zero count.
  for (const extension of ["social_autopsy", "intake_screen", "geography"]) {
    assert.ok(extensionCounts[extension], `missing extensionCounts entry for ${extension}`);
    const total = extensionCounts[extension].questions + extensionCounts[extension].sections + extensionCounts[extension].choices;
    assert.equal(total, 0, `${extension} unexpectedly contributed entries`);
  }
});

test("a layer-only question appears with its English label; a WHO base question does not appear", () => {
  const doc = readArtifact();

  // Present first: md_available (medical_records) really is in the artifact.
  const mdAvailable = doc.entries.find((e) => e.itemKind === "question" && e.itemKey === "md_available" && e.field === "label");
  assert.ok(mdAvailable, "md_available label entry is missing");
  assert.deepEqual(mdAvailable.extensions, ["medical_records"]);
  assert.ok(mdAvailable.text.length > 0);

  // Then what must be absent: a WHO base question never carried by DigitVA.
  const baseQuestion = doc.entries.find((e) => e.itemKey === "Id10010");
  assert.equal(baseQuestion, undefined);

  // sa01 is not yet authored in digitva-extension.ts: it must not appear
  // either, so this test does not accidentally pin a name that doesn't exist.
  const notYetAuthored = doc.entries.find((e) => e.itemKey === "sa01");
  assert.equal(notYetAuthored, undefined);
});

test("assertNoDot raises a clear error naming the offending item", () => {
  assert.throws(
    () => assertNoDot("Question name", "md.available", "digitva-extension.ts"),
    /md\.available/
  );
  // A name without a dot is left alone.
  assert.doesNotThrow(() => assertNoDot("Question name", "md_available", "digitva-extension.ts"));
});

test("an item contributed by two extensions carries both, and both extensions' counts include it", () => {
  const doc = readArtifact();

  // Present first: digitva_documents really is in the artifact, contributed
  // by both medical_records and death_summary (see digitva-extension.ts's
  // createDigitVaExtension, which emits the section whenever either is on).
  const digitvaDocuments = doc.entries.find(
    (e) => e.itemKind === "question" && e.itemKey === "digitva_documents" && e.field === "label"
  );
  assert.ok(digitvaDocuments, "digitva_documents label entry is missing");
  assert.deepEqual(digitvaDocuments.extensions, ["death_summary", "medical_records"]);

  // Then what must be absent: a single-extension item does not fan out to
  // extensions it was never attributed to.
  const mdAvailable = doc.entries.find((e) => e.itemKind === "question" && e.itemKey === "md_available");
  assert.deepEqual(mdAvailable.extensions, ["medical_records"]);

  // Both contributing extensions' counts include the shared section.
  assert.ok(doc.extensionCounts.medical_records.sections >= 1);
  assert.ok(doc.extensionCounts.death_summary.sections >= 1);
});

test("a DigitVA choice label diverging from an existing WHO base label throws", () => {
  assert.throws(
    () => assertChoiceLabelMatchesBase("YES_NO_REF", "yes", "Yeah", "Yes"),
    /YES_NO_REF\/yes/
  );
  // Matching labels are left alone.
  assert.doesNotThrow(() => assertChoiceLabelMatchesBase("YES_NO_REF", "yes", "Yes", "Yes"));
});

test("stableStringify sorts object keys and carries no timestamp-shaped field", () => {
  const first = stableStringify({ b: 1, a: 2, nested: { z: 1, y: 2 } });
  const second = stableStringify({ nested: { y: 2, z: 1 }, a: 2, b: 1 });
  assert.equal(first, second);
  assert.ok(first.indexOf('"a"') < first.indexOf('"b"'));

  const doc = readArtifact();
  assert.equal(JSON.stringify(doc).includes("built_at"), false);
  assert.equal(JSON.stringify(doc).includes("builtAt"), false);
});
