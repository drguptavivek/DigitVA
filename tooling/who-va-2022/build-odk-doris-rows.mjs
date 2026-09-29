// Emit vendor/who-va-2022/src/generated/odk-doris-support-rows.json: the
// XLSForm rows (survey, choices, and the changed WHO rows) for the
// doris_support_whova_2022 questions, read from the extension's own blocks
// (createDorisSupportExtension in vendor/who-va-2022/src/digitva-extension.ts),
// so web and ODK cannot drift (bead digitva-hln, first slice of digitva-aek).
// tooling/who-va-2022/build_odk_doris_rows.py turns this into the paste-ready
// workbook and Markdown against ND01's own header and row numbers.
//
//   cd tooling/who-va-2022 && npm run build:odk-doris-rows
//
// Expressions need no conversion: the extension already writes them in
// XLSForm syntax (`${name}`, `selected()`), and the web engine parses that
// same source. Determinism follows build-layer-reference.mjs (keys sorted,
// arrays in source order, no timestamp).
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { build } from "esbuild";

import { stableStringify } from "./build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const outPath = path.join(
  vendorSrc,
  "generated",
  "odk-doris-support-rows.json",
);

async function loadExtensionModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-odk-doris-rows-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  writeFileSync(
    entryPath,
    `export { createDorisSupportExtension, DORIS_SUPPORT_EXTENSION } from ${JSON.stringify(
      path.join(vendorSrc, "digitva-extension.js"),
    )};\n`,
  );
  try {
    await build({
      entryPoints: [entryPath],
      bundle: true,
      format: "esm",
      platform: "node",
      outfile,
      logLevel: "warning",
      nodePaths: [path.join(here, "node_modules")],
    });
    return await import(pathToFileURL(outfile).href);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

/**
 * The XLSForm `type` of an extension question. `base()` questions carry the
 * extension's own `digitva-extension` source type; they are free text.
 */
export function xlsformType(question) {
  if (question.sourceType !== "digitva-extension") return question.sourceType;
  if (question.control !== "text") {
    throw new Error(
      `${question.name}: no XLSForm type for control ${question.control}`,
    );
  }
  return "text";
}

/** One survey row, in XLSForm column names (English label and hint). */
export function surveyRow(question) {
  return {
    type: xlsformType(question),
    name: question.name,
    label: question.label?.en ?? "",
    hint: question.hint?.en ?? "",
    required: question.required ? "yes" : "",
    appearance: question.appearance ?? "",
    relevant: question.relevant?.source ?? "",
    constraint: question.constraint?.source ?? "",
    constraint_message: question.constraintMessage?.en ?? "",
  };
}

/** A DorisWhoChange as the XLSForm cells it replaces. */
export function changedCells(change) {
  const cells = {};
  if (change.relevant !== undefined) cells.relevant = change.relevant;
  if (change.constraint !== undefined) cells.constraint = change.constraint;
  if (change.constraintMessage !== undefined)
    cells.constraint_message = change.constraintMessage;
  if (change.required !== undefined)
    cells.required = change.required ? "yes" : "";
  return cells;
}

/** Every block's rows. A choice list is emitted with the first block that uses it. */
export function buildBlocks(blocks) {
  const listed = new Set();
  return blocks.map((block) => {
    if (
      block.questions.length &&
      !block.odk.after &&
      !block.odk.afterGroupEnd
    ) {
      throw new Error(`${block.id}: added questions but no ND01 position`);
    }
    const choices = [];
    for (const question of block.questions) {
      if (!question.listName || listed.has(question.listName)) continue;
      listed.add(question.listName);
      for (const choice of question.choices ?? []) {
        choices.push({
          list_name: question.listName,
          name: choice.value,
          label: choice.label?.en ?? "",
        });
      }
    }
    return {
      id: block.id,
      title: block.title,
      status: block.status,
      odk: block.odk,
      survey: block.questions.map(surveyRow),
      change: Object.entries(block.whoChanges).map(([name, change]) => ({
        name,
        cells: changedCells(change),
      })),
      choices,
    };
  });
}

async function main() {
  const { createDorisSupportExtension, DORIS_SUPPORT_EXTENSION } =
    await loadExtensionModule();
  // Section paths only place questions in the web form; ODK uses ND01 rows.
  const { blocks } = createDorisSupportExtension(0, () => []);
  const doc = {
    schemaVersion: 1,
    source: {
      generatedBy: "tooling/who-va-2022/build-odk-doris-rows.mjs",
      definition: "vendor/who-va-2022/src/digitva-extension.ts",
      extension: DORIS_SUPPORT_EXTENSION,
    },
    blocks: buildBlocks(blocks),
  };
  writeFileSync(outPath, `${stableStringify(doc)}\n`, "utf8");
  console.log(
    `wrote ${path.relative(repo, outPath)}: ${doc.blocks.length} blocks`,
  );
}

const isMainModule =
  process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (isMainModule) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
