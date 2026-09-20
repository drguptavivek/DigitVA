// Bundle the vendored WHO VA 2022 questionnaire (plus DigitVA's extension)
// into one ESM file served from app/static/vendor/who-va-2022/.
//
//   cd tooling/who-va-2022 && npm ci && npm run build
//
// The output is committed so deployments need no Node toolchain.
import { build } from "esbuild";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorDir = path.join(repo, "vendor", "who-va-2022");
const outDir = path.join(repo, "app", "static", "vendor", "who-va-2022");
mkdirSync(outDir, { recursive: true });

const entry = path.join(here, "entry.mjs");
const outfile = path.join(outDir, "who-va-2022.web-component.js");

await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  minify: true,
  sourcemap: false,
  target: ["es2020"],
  outfile,
  define: { "process.env.NODE_ENV": '"production"', __DEV__: "false" },
  nodePaths: [path.join(here, "node_modules")],
  alias: { "@digitva/who-va-2022": path.join(vendorDir, "src") },
  logLevel: "warning"
});

const bytes = readFileSync(outfile);
const version = JSON.parse(readFileSync(path.join(vendorDir, "package.json"), "utf8")).version;
// No built_at: the bundle is committed, so "when" is already git history,
// and a timestamp only made every rebuild dirty the manifest even when
// `bytes`/`sha256` -- the fields that actually identify this artifact --
// were unchanged (that's how the drift in 926c212 went unnoticed; see
// digitva-cw9). Regenerating on an unmodified tree must reproduce this file
// byte for byte, which a timestamp would break by construction.
const manifest = {
  package: "@drguptavivek/who-2022-va",
  vendored_version: version,
  file: path.basename(outfile),
  bytes: bytes.length,
  sha256: createHash("sha256").update(bytes).digest("hex")
};
writeFileSync(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`built ${path.relative(repo, outfile)} ${(bytes.length / 1024).toFixed(0)} KB`);
