// Emit vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json:
// every question and section of the composed instrument (WHO base plus all
// DigitVA extensions, i.e. exactly whoVa2022Instrument from
// vendor/who-va-2022/src/instrument.ts), reduced to the fields a server-side
// re-evaluation needs -- name, sectionPath, control, and the *source strings*
// of relevant/constraint/calculation -- so app/services/web_intake_service.py
// can re-derive relevance and validity without a Node process in the request
// path. See beads digitva-cal.2 and digitva-aiy.1.
//
// Deliberately source strings, not the TypeScript engine's own parsed AST:
// app/services/xform_expression_evaluator.py already has a parser
// (parse_expression) proven against expression-conformance-corpus.json, so
// re-parsing here would be a second, unverified AST shape to keep in sync.
// One parser, fed by this file's strings, is the smaller surface.
//
//   cd tooling/who-va-2022 && npm run build:server-instrument
//
// Determinism follows build-layer-reference.mjs's pattern (object keys
// sorted, arrays kept in source order, no timestamp) so an unmodified tree
// reproduces this file byte for byte.
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { build } from "esbuild";

import { stableStringify } from "./build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const outPath = path.join(
  repo,
  "vendor",
  "who-va-2022",
  "src",
  "generated",
  "who-va-2022.server-instrument.json"
);

async function loadInstrumentModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-server-instrument-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  writeFileSync(
    entryPath,
    `export { whoVa2022Instrument } from ${JSON.stringify(path.join(vendorSrc, "instrument.js"))};`
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

async function main() {
  const { whoVa2022Instrument } = await loadInstrumentModule();

  const sections = whoVa2022Instrument.sections.map((section) => ({
    name: section.name,
    parent: section.parent ?? null,
    relevant: section.relevant?.source ?? null
  }));

  const questions = whoVa2022Instrument.questions.map((question) => ({
    name: question.name,
    sectionPath: question.sectionPath,
    control: question.control,
    dataType: question.dataType,
    relevant: question.relevant?.source ?? null,
    constraint: question.constraint?.source ?? null,
    calculation: question.calculation?.source ?? null
  }));

  const output = {
    schemaVersion: 1,
    source: {
      instrumentId: whoVa2022Instrument.id,
      instrumentVersion: whoVa2022Instrument.version
    },
    sections,
    questions
  };

  writeFileSync(outPath, `${stableStringify(output)}\n`, "utf8");
  console.log(`Wrote ${questions.length} questions, ${sections.length} sections -> ${outPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
