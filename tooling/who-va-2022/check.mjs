// Sanity checks on the vendored instrument plus DigitVA extension: run after
// editing vendor/who-va-2022/src/digitva-extension.ts.
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const here = path.dirname(fileURLToPath(import.meta.url));
const vendorSrc = path.resolve(here, "..", "..", "vendor", "who-va-2022", "src");
const tmp = mkdtempSync(path.join(tmpdir(), "whova-check-"));
const out = path.join(tmp, "headless.mjs");
await build({
  entryPoints: [path.join(vendorSrc, "index.ts")],
  bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "warning",
  nodePaths: [path.join(here, "node_modules")]
});
const mod = await import(pathToFileURL(out).href);
const inst = mod.whoVa2022Instrument;
const names = new Set(inst.questions.map((q) => q.name));
const expected = ["narr_language", "imagenarr", "md_count", "md_im1", "md_im30", "ds_count", "ds_im5", "comment", "custom_medical_certificate_upload"];
const missing = expected.filter((n) => !names.has(n));
if (missing.length) throw new Error("missing DigitVA questions: " + missing.join(", "));
const dup = inst.questions.map((q) => q.name).filter((n, i, a) => a.indexOf(n) !== i);
if (dup.length) throw new Error("duplicate question names: " + dup.join(", "));
const r = mod.validateSubmission(inst, { Id10013: "yes", md_count: 2, md_im1: "who-va-attachment:x" });
const relevantImages = inst.questions.filter((q) => /^md_im\d+$/.test(q.name) && mod.isQuestionRelevant(inst, q, { Id10013: "yes", md_count: 2 })).map((q) => q.name);
console.log(JSON.stringify({ questions: inst.questions.length, sections: inst.sections.length, relevantImagesWhenCount2: relevantImages, sampleIssues: r.issues.length }));
writeFileSync(path.join(tmp, "ok"), "");
