// Bundle the vendored questionnaire's headless validator for Node.
//
//   cd tooling/who-va-2022 && npm ci && npm run build:validator
//
// The browser bundle (build.mjs) and this one share the same vendored source,
// so the questionnaire the interviewer fills and the validator the server
// trusts are the same instrument — that is the whole point of decision W1 in
// docs/planning/who-va-2022-web-intake-plan.md.
//
// Bundling (rather than importing the TypeScript sources at runtime) keeps the
// validator service free of a TypeScript loader and pins exactly what it runs.
import { build } from "esbuild";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorDir = path.join(repo, "vendor", "who-va-2022");
const outDir = path.join(here, "dist-node");
const outfile = path.join(outDir, "validator-bundle.mjs");

mkdirSync(outDir, { recursive: true });

await build({
  stdin: {
    contents: [
      'export { validateSubmission } from "@digitva/who-va-2022/index.ts";',
      'export { whoVa2022Instrument } from "@digitva/who-va-2022/instrument.ts";',
      'export { WHO_VA_FORM_VERSION } from "@digitva/who-va-2022/version.ts";',
    ].join("\n"),
    resolveDir: here,
    sourcefile: "validator-entry.mjs",
    loader: "js",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  target: ["node20"],
  minify: false,
  sourcemap: false,
  outfile,
  define: { "process.env.NODE_ENV": '"production"', __DEV__: "false" },
  nodePaths: [path.join(here, "node_modules")],
  alias: { "@digitva/who-va-2022": path.join(vendorDir, "src") },
  logLevel: "warning",
});

const bytes = readFileSync(outfile);
const version = JSON.parse(readFileSync(path.join(vendorDir, "package.json"), "utf8")).version;
writeFileSync(
  path.join(outDir, "manifest.json"),
  JSON.stringify(
    {
      package: "@drguptavivek/who-2022-va",
      vendored_version: version,
      built_at: new Date().toISOString(),
      file: path.basename(outfile),
      bytes: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    },
    null,
    2,
  ) + "\n",
);
console.log(`built ${path.relative(repo, outfile)} ${(bytes.length / 1024).toFixed(0)} KB`);
