// Emit vendor/who-va-2022/src/generated/digitva-layers.reference.json: the
// DigitVA-only questions, sections and choices that createWhoVa2022Instrument
// splices into the WHO base instrument, keyed the way Python's
// instrument_translation_service already keys reference strings, so a later
// change can teach that service about the layer questions without hand
// transcribing names out of digitva-extension.ts.
//
//   cd tooling/who-va-2022 && npm run build:layer-reference
//
// How the delta is found (deliberately: no hardcoded question-name list, so
// this cannot drift from digitva-extension.ts):
//   1. Read the generated WHO base instrument JSON directly (it is never
//      touched by DigitVA's extension) to get the base question/section/choice
//      names.
//   2. Call createWhoVa2022Instrument([]) — every DigitVA extension off. Per
//      instrument.ts, digitva_core (custom_medical_certificate_upload,
//      consent_mode) is spliced in unconditionally, so whatever is new here
//      relative to the base is digitva_core's contribution.
//   3. For each of the other seven names in ALL_DIGITVA_EXTENSIONS, call
//      createWhoVa2022Instrument([name]) and diff against step 2's result.
//      Whatever is new is that one extension's contribution (empty for
//      social_autopsy / intake_screen / geography, which gate content outside
//      this module — see digitva-extension.ts's own header comment).
//   4. Cross-check that the union of every per-extension delta equals the
//      delta of createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS) against the
//      base, so an unexpected interaction between extensions cannot go
//      unnoticed.
//
// Output shape (see also the JSDoc-style comment further down, next to
// buildEntries): { schemaVersion, source: {...}, extensionCounts: {...},
// entries: [{ itemKind, itemKey, field, extensions, text }, ...] }, matching
// the (item_kind, item_key, field) -> english_text shape
// app/services/instrument_translation_service.py already keys reference
// strings by. `itemKind` is "question" (a survey question OR a section/group
// — instrument_translation_service.py's own resource_id() treats a group as
// a "question" row) or "choice"; `itemKey` is the question/section name, or
// "<list_name>/<choice_value>" for a choice. `field` is "label", "hint" or
// "guidance_hint" (a choice only ever carries "label"). `extensions` is a
// sorted, non-empty array: usually one DigitVA extension, but an item (e.g.
// the digitva_documents section) that more than one extension emits carries
// every contributor, so per-layer coverage can key on any of them without
// missing one that a first-match-wins pick would have hidden.
//
// Determinism is load-bearing (see the module docstring in
// instrument_translation_service.py and beads digitva-cw9): no timestamp, no
// build id. Object keys are written in sorted order and entries are sorted by
// (itemKind, itemKey, field) so re-running this on an unmodified tree
// reproduces the committed file byte for byte.
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const generatedDir = path.join(vendorSrc, "generated");
const basePath = path.join(generatedDir, "who-va-2022.instrument.json");
const outPath = path.join(generatedDir, "digitva-layers.reference.json");
const vendorPackage = JSON.parse(readFileSync(path.join(repo, "vendor", "who-va-2022", "package.json"), "utf8"));

/** Question fields Python's translation service keys, mapped to its field names. */
const QUESTION_FIELDS = [
  ["label", "label"],
  ["hint", "hint"],
  ["guidance", "guidance_hint"]
];

export function assertNoDot(kind, value, where) {
  if (value.includes(".")) {
    throw new Error(
      `${kind} ${JSON.stringify(value)} (${where}) contains a literal '.', which would corrupt the ` +
        "dotted XLIFF resource ids app/services/instrument_translation_service.py builds " +
        "(question.<name>.<field> / choice.<list>.<name>.<field>)."
    );
  }
}

function englishText(localized) {
  return typeof localized?.en === "string" ? localized.en.trim() : "";
}

async function loadInstrumentModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-layer-reference-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  // A synthetic entry re-exporting what digitva-extension.ts/instrument.ts
  // keep internal to the vendored package (index.ts does not re-export
  // ALL_DIGITVA_EXTENSIONS). ".js" specifiers resolving to the sibling ".ts"
  // files mirror how the vendored sources import each other; esbuild follows
  // the same convention build.mjs and check.mjs already rely on.
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

export function diffByName(after, before, key) {
  const beforeNames = new Set(before.map((item) => item[key]));
  return after.filter((item) => !beforeNames.has(item[key]));
}

function baseChoiceLabels(instrument) {
  const labels = new Map();
  for (const question of instrument.questions) {
    if (!question.choices || !question.listName) continue;
    for (const choice of question.choices) {
      labels.set(`${question.listName}/${choice.value}`, englishText(choice.label));
    }
  }
  return labels;
}

/**
 * A choice key (`<list>/<value>`) already in the WHO base must keep the WHO
 * base's label text: Python's translation reference keys off the base label,
 * so a diverging DigitVA label at the same key would be silently dropped
 * rather than translated. Throws (in `assertNoDot`'s style) instead of
 * letting that happen quietly.
 */
export function assertChoiceLabelMatchesBase(listName, value, digitvaLabel, baseLabel) {
  if (digitvaLabel !== baseLabel) {
    throw new Error(
      `Choice ${JSON.stringify(`${listName}/${value}`)} already exists in the WHO base instrument with a ` +
        `different label: DigitVA label ${JSON.stringify(digitvaLabel)} vs base label ${JSON.stringify(baseLabel)}. ` +
        "Python's translation reference keys this choice off the base label, so the DigitVA label would be " +
        "silently ignored -- give it the same label as the base, or a new list/value pair."
    );
  }
}

export function buildEntries({ questionAttribution, sectionAttribution, composedAll, baseChoices }) {
  const questionsByName = new Map(composedAll.questions.map((q) => [q.name, q]));
  const sectionsByName = new Map(composedAll.sections.map((s) => [s.name, s]));
  const entries = [];
  // A choice list can be reused across more than one question attributed to
  // the same layer (e.g. social_autopsy's `sa_tu` on sa_tu13..sa_tu19, or
  // `YES_NO_DK` on sa10/sa12): key by (itemKind, itemKey, field) so the
  // second question referencing the same list/value contributes its
  // extensions to the existing entry instead of pushing a second, duplicate
  // one -- which would collide with itself once merged in Python's
  // reference_items().
  const choiceEntriesByKey = new Map();

  for (const [name, extensions] of sectionAttribution) {
    assertNoDot("Section name", name, "digitva-extension.ts");
    const section = sectionsByName.get(name);
    const text = englishText(section.label);
    const extensionList = [...extensions].sort();
    if (text) entries.push({ itemKind: "question", itemKey: name, field: "label", extensions: extensionList, text });
  }

  for (const [name, extensions] of questionAttribution) {
    assertNoDot("Question name", name, "digitva-extension.ts");
    const question = questionsByName.get(name);
    const extensionList = [...extensions].sort();
    for (const [sourceField, pyField] of QUESTION_FIELDS) {
      const text = englishText(question[sourceField]);
      if (text) entries.push({ itemKind: "question", itemKey: name, field: pyField, extensions: extensionList, text });
    }
    if (!question.choices || !question.listName) continue;
    assertNoDot("Choice list name", question.listName, `question ${name}`);
    for (const choice of question.choices) {
      assertNoDot("Choice value", choice.value, `list ${question.listName}`);
      const key = `${question.listName}/${choice.value}`;
      const text = englishText(choice.label);
      if (baseChoices.has(key)) {
        // Already a WHO base choice: Python's reference already has it, as
        // long as the label text actually matches -- assert that rather than
        // silently trusting the shared key.
        assertChoiceLabelMatchesBase(question.listName, choice.value, text, baseChoices.get(key));
        continue;
      }
      if (!text) continue;
      const existing = choiceEntriesByKey.get(key);
      if (existing) {
        if (existing.text !== text) {
          throw new Error(
            `Choice ${JSON.stringify(key)} is authored with two different labels across questions ` +
              `sharing its list (${JSON.stringify(existing.text)} vs ${JSON.stringify(text)}).`
          );
        }
        for (const extension of extensions) existing.extensions.add(extension);
        continue;
      }
      const entry = { itemKind: "choice", itemKey: key, field: "label", extensions: new Set(extensions), text };
      choiceEntriesByKey.set(key, entry);
      entries.push(entry);
    }
  }

  // Freeze each choice entry's accumulated extension set into the same
  // sorted array shape every other entry carries.
  for (const entry of choiceEntriesByKey.values()) {
    entry.extensions = [...entry.extensions].sort();
  }

  entries.sort((a, b) => {
    if (a.itemKind !== b.itemKind) return a.itemKind < b.itemKind ? -1 : 1;
    if (a.itemKey !== b.itemKey) return a.itemKey < b.itemKey ? -1 : 1;
    return a.field < b.field ? -1 : a.field > b.field ? 1 : 0;
  });
  return entries;
}

export function stableStringify(value, indent = "") {
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const inner = value.map((item) => `${indent}  ${stableStringify(item, indent + "  ")}`).join(",\n");
    return `[\n${inner}\n${indent}]`;
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value).sort();
    if (keys.length === 0) return "{}";
    const inner = keys
      .map((key) => `${indent}  ${JSON.stringify(key)}: ${stableStringify(value[key], indent + "  ")}`)
      .join(",\n");
    return `{\n${inner}\n${indent}}`;
  }
  return JSON.stringify(value);
}

async function main() {
  const base = JSON.parse(readFileSync(basePath, "utf8"));
  const baseQuestionNames = new Set(base.questions.map((q) => q.name));
  const baseSectionNames = new Set(base.sections.map((s) => s.name));
  const baseChoices = baseChoiceLabels(base);

  const { createWhoVa2022Instrument, ALL_DIGITVA_EXTENSIONS } = await loadInstrumentModule();

  const emptyComposed = createWhoVa2022Instrument([]);
  // name -> Set of contributing extension names. An item (in practice, so
  // far, only the digitva_documents section) can be emitted by more than one
  // extension; the set carries every contributor rather than picking the
  // first one seen, so per-layer coverage can key on any of them.
  const questionAttribution = new Map();
  const sectionAttribution = new Map();

  for (const name of diffByName(emptyComposed.questions, base.questions, "name").map((q) => q.name)) {
    if (!baseQuestionNames.has(name)) questionAttribution.set(name, new Set(["digitva_core"]));
  }
  for (const name of diffByName(emptyComposed.sections, base.sections, "name").map((s) => s.name)) {
    if (!baseSectionNames.has(name)) sectionAttribution.set(name, new Set(["digitva_core"]));
  }

  const extensionCounts = {};
  for (const extension of ALL_DIGITVA_EXTENSIONS) {
    if (extension === "digitva_core") continue;
    const composed = createWhoVa2022Instrument([extension]);
    const newQuestions = diffByName(composed.questions, emptyComposed.questions, "name");
    const newSections = diffByName(composed.sections, emptyComposed.sections, "name");
    for (const question of newQuestions) {
      if (!questionAttribution.has(question.name)) questionAttribution.set(question.name, new Set());
      questionAttribution.get(question.name).add(extension);
    }
    for (const section of newSections) {
      if (!sectionAttribution.has(section.name)) sectionAttribution.set(section.name, new Set());
      sectionAttribution.get(section.name).add(extension);
    }
  }

  // Cross-check: the union of every per-extension delta must equal the delta
  // of turning every extension on at once, so an interaction between two
  // extensions (were one ever added) cannot silently go unrepresented.
  const composedAll = createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS);
  const allNewQuestionNames = new Set(
    diffByName(composedAll.questions, base.questions, "name").map((q) => q.name)
  );
  const allNewSectionNames = new Set(diffByName(composedAll.sections, base.sections, "name").map((s) => s.name));
  const attributedQuestionNames = new Set(questionAttribution.keys());
  const attributedSectionNames = new Set(sectionAttribution.keys());
  const missingQuestions = [...allNewQuestionNames].filter((n) => !attributedQuestionNames.has(n));
  const extraQuestions = [...attributedQuestionNames].filter((n) => !allNewQuestionNames.has(n));
  const missingSections = [...allNewSectionNames].filter((n) => !attributedSectionNames.has(n));
  const extraSections = [...attributedSectionNames].filter((n) => !allNewSectionNames.has(n));
  if (missingQuestions.length || extraQuestions.length || missingSections.length || extraSections.length) {
    throw new Error(
      "Per-extension composition did not reconcile with all-extensions composition: " +
        JSON.stringify({ missingQuestions, extraQuestions, missingSections, extraSections })
    );
  }

  const entries = buildEntries({ questionAttribution, sectionAttribution, composedAll, baseChoices });

  for (const extension of ALL_DIGITVA_EXTENSIONS) {
    extensionCounts[extension] = {
      questions: [...questionAttribution.values()].filter((exts) => exts.has(extension)).length,
      sections: [...sectionAttribution.values()].filter((exts) => exts.has(extension)).length,
      choices: entries.filter((e) => e.itemKind === "choice" && e.extensions.includes(extension)).length
    };
  }

  const doc = {
    schemaVersion: 2,
    source: {
      generatedBy: "tooling/who-va-2022/build-layer-reference.mjs",
      package: vendorPackage.name,
      vendoredVersion: vendorPackage.version,
      baseInstrument: "vendor/who-va-2022/src/generated/who-va-2022.instrument.json",
      extensions: ALL_DIGITVA_EXTENSIONS
    },
    extensionCounts,
    entries
  };

  writeFileSync(outPath, stableStringify(doc) + "\n");
  const totalsByExtension = Object.fromEntries(
    Object.entries(extensionCounts).map(([ext, counts]) => [ext, counts.questions + counts.sections + counts.choices])
  );
  console.log(
    `wrote ${path.relative(repo, outPath)}: ${entries.length} entries; per-extension item counts ${JSON.stringify(totalsByExtension)}`
  );
}

const isMainModule = process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (isMainModule) await main();
