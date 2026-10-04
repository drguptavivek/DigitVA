// Emit app/data/who-va-2022.composed.json: the WHO VA 2022 instrument with
// EVERY DigitVA extension composed in (createWhoVa2022Instrument(
// ALL_DIGITVA_EXTENSIONS), whoOverrides left at its default `true` -- the form
// the app renders), the full definition kept, and every section/question a
// conditional extension contributes tagged `extensions: [..]`. The server
// (app/services/served_form_service.py) serves this file per project by
// dropping the items whose tags are all disabled, so no Node process sits in
// the request path. Beads digitva-6pwq / digitva-xuf9; policy:
// docs/policy/field-data-collection.md "Form definition from the server".
//
//   cd tooling/who-va-2022 && npm run build:composed-instrument
//
// Tagging: an item is tagged E when compose(always-on + E) has its name and
// compose(always-on) does not. A shared section (digitva_documents:
// medical_records and death_summary) carries both tags. digitva_core and doris_support_whova_2022 are always on (see
// _enabled_extensions in app/routes/api/organization.py) and intake_screen /
// geography contribute no content, so none of them is tagged.
//
// The build fails unless, for all 2^5 subsets S of the conditional extensions,
// filter(tagged, S) equals compose(always-on + S): same section and question
// names in the same order, and every item deep-equal. `order` is the one
// field allowed to differ -- createDigitVaExtension numbers its questions with
// a running counter, so a subset that omits a layer renumbers the layers after
// it. Nothing reads `order` to place a question (array position does, see
// instrument.ts), so the check ignores it but counts and reports the
// differences instead of hiding them.
//
// Version: `<WHO version>-<first 10 hex of sha256 over the canonical
// (stableStringify) untagged composed-ALL definition>`, so any change to any
// question, label or rule moves it. `engineVersion` is the schema/engine
// contract the definition needs; the vendor package exports no engine version,
// so the number lives here and the Expo session must add the matching constant
// to the app's engine and refuse a higher one.
//
// Deterministic like the other generated files (sorted keys, no timestamp).
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import assert from "node:assert/strict";
import { build } from "esbuild";

import { stableStringify } from "./build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const outPath = path.join(repo, "app", "data", "who-va-2022.composed.json");

export const ENGINE_VERSION = 1;
const ALWAYS_ON = ["digitva_core", "doris_support_whova_2022"];
const CONDITIONAL = ["social_autopsy", "narration_language", "death_summary", "medical_records", "abha"];

async function loadInstrumentModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-composed-instrument-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  writeFileSync(
    entryPath,
    [
      `export { createWhoVa2022Instrument } from ${JSON.stringify(path.join(vendorSrc, "instrument.js"))};`,
      `export { ALL_DIGITVA_EXTENSIONS } from ${JSON.stringify(path.join(vendorSrc, "digitva-extension.js"))};`
    ].join("\n")
  );
  try {
    await build({
      entryPoints: [entryPath],
      bundle: true,
      format: "esm",
      platform: "node",
      outfile,
      logLevel: "warning",
      nodePaths: [path.join(here, "node_modules")]
    });
    return await import(pathToFileURL(outfile).href);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

const names = (items) => items.map((item) => item.name);
const withoutOrder = ({ order, ...rest }) => rest;

/** Index sequence a stable sort by `order` gives, with a tie marker between equal orders. */
function orderShape(items) {
  const sorted = items.map((item, index) => ({ index, order: item.order })).sort((a, b) => a.order - b.order || a.index - b.index);
  return sorted.map((entry, i) => (i > 0 && sorted[i - 1].order === entry.order ? `=${entry.index}` : `${entry.index}`));
}

/** Tag every item the conditional extensions contribute; returns the tagged definition. */
function tagDefinition(all, compose) {
  const tags = { sections: new Map(), questions: new Map() };
  const base = compose(ALWAYS_ON);
  for (const extension of CONDITIONAL) {
    // Diffing against compose(ALL minus E) would miss a shared section (both
    // medical_records and death_summary emit digitva_documents, so removing
    // either one leaves it behind); diffing the extension alone against the
    // always-on base finds every contributor of every item.
    const alone = compose([...ALWAYS_ON, extension]);
    for (const kind of ["sections", "questions"]) {
      const baseNames = new Set(names(base[kind]));
      const aloneNames = new Set(names(alone[kind]));
      for (const item of all[kind]) {
        if (baseNames.has(item.name) || !aloneNames.has(item.name)) continue;
        if (!tags[kind].has(item.name)) tags[kind].set(item.name, []);
        tags[kind].get(item.name).push(extension);
      }
    }
  }
  const tag = (kind) =>
    all[kind].map((item) => (tags[kind].has(item.name) ? { ...item, extensions: tags[kind].get(item.name).sort() } : item));
  return { ...all, sections: tag("sections"), questions: tag("questions") };
}

/** Item kept for subset S when untagged or any tag is enabled (the server's rule). */
const keep = (enabled) => (item) => !item.extensions || item.extensions.some((name) => enabled.has(name));

/** The 2^5 equivalence check; throws on any difference but `order`. */
function checkSubsets(tagged, compose) {
  let subsets = 0;
  let orderDiffs = 0;
  for (let mask = 0; mask < 1 << CONDITIONAL.length; mask += 1) {
    const subset = CONDITIONAL.filter((_, bit) => mask & (1 << bit));
    const enabled = new Set(subset);
    const label = `[${subset.join(", ") || "none"}]`;
    const composed = compose([...ALWAYS_ON, ...subset]);
    for (const kind of ["sections", "questions"]) {
      const filtered = tagged[kind].filter(keep(enabled));
      assert.deepEqual(names(filtered), names(composed[kind]), `${kind} names/order differ for ${label}`);
      // engine/instrument-model.ts sorts sibling sections by `order`, so the
      // renumbering must keep every relative order (and tie) intact.
      assert.deepEqual(orderShape(filtered), orderShape(composed[kind]), `${kind} relative order differs for ${label}`);
      filtered.forEach((item, index) => {
        const expected = composed[kind][index];
        const { extensions, ...actual } = item;
        assert.deepEqual(withoutOrder(actual), withoutOrder(expected), `${kind} ${item.name} differs for ${label}`);
        if (actual.order !== expected.order) orderDiffs += 1;
      });
    }
    subsets += 1;
  }
  return { subsets, orderDiffs };
}

async function main() {
  const { createWhoVa2022Instrument, ALL_DIGITVA_EXTENSIONS } = await loadInstrumentModule();
  // Round-trip through JSON so the check compares what is written to disk.
  const compose = (extensions) => JSON.parse(JSON.stringify(createWhoVa2022Instrument(extensions)));

  const all = compose(ALL_DIGITVA_EXTENSIONS);
  const sha10 = createHash("sha256").update(stableStringify(all)).digest("hex").slice(0, 10);
  const tagged = tagDefinition(all, compose);

  const { subsets, orderDiffs } = checkSubsets(tagged, compose);
  const tagCounts = Object.fromEntries(CONDITIONAL.map((name) => [name, 0]));
  for (const item of [...tagged.sections, ...tagged.questions]) {
    for (const name of item.extensions ?? []) tagCounts[name] += 1;
  }

  const output = { ...tagged, version: `${all.version}-${sha10}`, engineVersion: ENGINE_VERSION };
  mkdirSync(path.dirname(outPath), { recursive: true });
  writeFileSync(outPath, `${stableStringify(output)}\n`, "utf8");
  console.log(
    `Wrote ${tagged.questions.length} questions, ${tagged.sections.length} sections, version ${output.version} -> ${outPath}`
  );
  console.log(`Tagged items per extension: ${JSON.stringify(tagCounts)}`);
  console.log(`Subset check: ${subsets}/32 subsets match compose(); \`order\` differs in ${orderDiffs} item placements (absolute numbers only; relative order verified identical)`);
}

const isMainModule = process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (isMainModule) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
