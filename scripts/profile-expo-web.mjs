/**
 * Profile an already-exported Expo web bundle without executing its JavaScript.
 *
 * This is intentionally a small, file-only CI check.  It reads the generated
 * HTML and asset manifest, hashes files, and measures deterministic gzip bytes.
 * It must not be used with a directory containing clinical or private data.
 */
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

export const INITIAL_RAW_LIMIT = 3_266_788;
export const INITIAL_GZIP_LIMIT = 813_650;
export const CANONICAL_WHO_INSTRUMENT_MARKER = "2022whova_xls_form_for_odk_multilingual.xlsx";

const MAX_FILES = 4096;
const MAX_FILE_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_BYTES = 100 * 1024 * 1024;
const SAFE_NAME = /^[A-Za-z0-9_.@()-]+$/;
const SHA256 = /^[a-f0-9]{64}$/;
const SOURCE_COMMIT = /^[a-f0-9]{40}$/;
const RELEASE = /^[A-Za-z0-9._-]{1,100}$/;
const WHO_PACKAGE_NAME = "@drguptavivek/who-2022-va";
const SEMVER = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

function assertWithin(root, candidate, label) {
  const rootPath = resolve(root);
  const candidatePath = resolve(candidate);
  if (candidatePath !== rootPath && !candidatePath.startsWith(`${rootPath}${sep}`)) {
    throw new Error(`${label} escapes the export directory`);
  }
}

function safeExportPath(dist, relativePath, label = "asset") {
  if (!relativePath || relativePath.includes("\0") || relativePath.includes("\\")) {
    throw new Error(`Unsafe ${label} path`);
  }
  const pieces = relativePath.split("/");
  if (pieces.some((piece) => !piece || piece === "." || piece === ".." || !SAFE_NAME.test(piece))) {
    throw new Error(`Unsafe ${label} path`);
  }
  const filePath = resolve(dist, relativePath);
  assertWithin(dist, filePath, label);
  if (!existsSync(filePath)) throw new Error(`Missing ${label}: ${relativePath}`);
  const info = lstatSync(filePath);
  if (info.isSymbolicLink() || !info.isFile()) throw new Error(`Unsafe ${label}: ${relativePath}`);
  const resolved = realpathSync(filePath);
  assertWithin(dist, resolved, label);
  return { filePath, path: `/app/${relativePath}` };
}

function decodeLocalUrl(value, label) {
  if (typeof value !== "string" || !value.startsWith("/app/")) {
    throw new Error(`External or unsupported ${label} URL: ${String(value)}`);
  }
  if (value.includes("?") || value.includes("#")) {
    throw new Error(`Query or fragment is not allowed in ${label} URL: ${value}`);
  }
  let decoded;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    throw new Error(`Malformed ${label} URL: ${value}`);
  }
  if (decoded !== value || decoded.includes("\\") || decoded.includes("\0")) {
    throw new Error(`Encoded or unsafe ${label} URL: ${value}`);
  }
  return decoded.slice("/app/".length);
}

function attribute(tag, name) {
  const match = tag.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"));
  return match?.[1] ?? match?.[2] ?? match?.[3];
}

/** Return script[src] resources in the order they occur in generated HTML. */
export function parseInitialScripts(html) {
  const matches = [];
  const tags = /<script\b[^>]*>/gi;
  for (let match = tags.exec(html); match; match = tags.exec(html)) {
    const tag = match[0];
    const src = attribute(tag, "src");
    if (src) matches.push({ kind: "script", url: src, offset: match.index });
  }
  return matches.sort((a, b) => a.offset - b.offset).map(({ kind, url }) => ({ kind, url }));
}

function collectExpoJavaScript(dist) {
  const files = [];
  let total = 0;
  function visit(relativeDirectory) {
    const directory = join(dist, relativeDirectory);
    const entries = readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      if (!SAFE_NAME.test(entry.name) || entry.name.startsWith(".")) throw new Error(`Unsafe export name: ${entry.name}`);
      const child = relativeDirectory ? `${relativeDirectory}/${entry.name}` : entry.name;
      const childPath = join(dist, child);
      if (entry.isSymbolicLink()) throw new Error(`Symlink in export: ${child}`);
      if (entry.isDirectory()) {
        visit(child);
        continue;
      }
      if (!entry.isFile() || extname(entry.name).toLowerCase() !== ".js") continue;
      const size = lstatSync(childPath).size;
      total += size;
      if (files.length >= MAX_FILES || size > MAX_FILE_BYTES || total > MAX_TOTAL_BYTES) {
        throw new Error("Oversized JavaScript export");
      }
      files.push(child);
    }
  }
  const expo = join(dist, "_expo");
  if (existsSync(expo)) {
    if (lstatSync(expo).isSymbolicLink()) throw new Error("Symlink in export: _expo");
    visit("_expo");
  }
  return files;
}

function readManifest(dist, manifestPath) {
  const manifestRelative = relative(dist, manifestPath);
  assertWithin(dist, manifestPath, "manifest");
  const identity = safeExportPath(dist, manifestRelative, "manifest");
  if (identity.path !== "/app/asset-manifest.json") {
    throw new Error("Manifest must be inside the export root");
  }
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(identity.filePath, "utf8"));
  } catch (error) {
    throw new Error(`Invalid asset manifest: ${error.message}`);
  }
  if (!manifest || !RELEASE.test(manifest.release ?? "") || !SOURCE_COMMIT.test(manifest.source_commit ?? "")) {
    throw new Error("Asset manifest has invalid release identity");
  }
  if (!Array.isArray(manifest.assets) || manifest.assets.length > MAX_FILES) {
    throw new Error("Asset manifest has an invalid asset list");
  }
  for (const asset of manifest.assets) {
    if (!asset || typeof asset.path !== "string" || !SHA256.test(asset.sha256 ?? "")) {
      throw new Error("Asset manifest has an invalid asset entry");
    }
    const path = decodeLocalUrl(asset.path, "manifest asset");
    const local = safeExportPath(dist, path, "manifest asset");
    const bytes = readFileSync(local.filePath);
    if (asset.size !== bytes.byteLength || sha256(bytes) !== asset.sha256) {
      throw new Error(`Manifest hash or size mismatch: ${asset.path}`);
    }
  }
  return manifest;
}

function validateWhoComponent(manifest, { required, initialPaths, deferred, assetsByPath }) {
  const component = manifest.components?.who;
  if (!required) return component ?? null;
  if (!component || typeof component !== "object" || Array.isArray(component)) {
    throw new Error("Required WHO component metadata is missing");
  }
  const componentKeys = ["package_name", "package_version", "source_commit", "artifact_sha256", "dist_sha256"];
  if (JSON.stringify(Object.keys(component).sort()) !== JSON.stringify(componentKeys.sort())) {
    throw new Error("WHO component metadata has an unexpected schema");
  }
  if (component.package_name !== WHO_PACKAGE_NAME) throw new Error("WHO component package_name is invalid");
  if (typeof component.package_version !== "string" || !SEMVER.test(component.package_version)) {
    throw new Error("WHO component package_version is invalid");
  }
  if (component.source_commit !== manifest.source_commit) throw new Error("WHO component source_commit does not match the app manifest");
  for (const field of ["artifact_sha256", "dist_sha256"]) {
    if (typeof component[field] !== "string" || !SHA256.test(component[field])) throw new Error(`WHO component ${field} is invalid`);
  }
  if (!Array.isArray(manifest.groups?.interviewRuntime) || manifest.groups.interviewRuntime.length === 0) {
    throw new Error("Required WHO interviewRuntime group is empty or missing");
  }
  const groupPaths = new Set();
  let groupHasCanonicalChunk = false;
  for (const path of manifest.groups.interviewRuntime) {
    if (typeof path !== "string" || groupPaths.has(path)) throw new Error("WHO interviewRuntime group contains a duplicate or invalid path");
    groupPaths.add(path);
    const asset = assetsByPath.get(path);
    if (!asset || asset.cacheable !== true || !path.toLowerCase().endsWith(".js")) {
      throw new Error(`WHO interviewRuntime group contains a non-cacheable asset: ${path}`);
    }
    if (initialPaths.has(path)) throw new Error(`WHO interviewRuntime asset must be deferred: ${path}`);
    const chunk = deferred.find((entry) => entry.path === path);
    if (chunk?.contains_canonical_instrument_marker) groupHasCanonicalChunk = true;
  }
  if (!groupHasCanonicalChunk) throw new Error("WHO interviewRuntime group does not include the canonical deferred instrument chunk");
  return {
    package_name: component.package_name,
    package_version: component.package_version,
    source_commit: component.source_commit,
    artifact_sha256: component.artifact_sha256,
    dist_sha256: component.dist_sha256,
  };
}

function measure(dist, relativePath, kind) {
  const local = safeExportPath(dist, relativePath, kind);
  const bytes = readFileSync(local.filePath);
  if (bytes.byteLength > MAX_FILE_BYTES) throw new Error(`Oversized ${kind}: ${relativePath}`);
  return {
    path: local.path,
    kind,
    raw_bytes: bytes.byteLength,
    gzip_bytes: gzipSync(bytes, { level: 9, mtime: 0 }).byteLength,
    sha256: sha256(bytes),
    contains_canonical_instrument_marker: bytes.includes(CANONICAL_WHO_INSTRUMENT_MARKER),
  };
}

function totals(entries) {
  return entries.reduce((result, entry) => ({
    raw_bytes: result.raw_bytes + entry.raw_bytes,
    gzip_bytes: result.gzip_bytes + entry.gzip_bytes,
  }), { raw_bytes: 0, gzip_bytes: 0 });
}

/** Build and write the deterministic CI bundle profile. */
export function profileExpoWeb({ dist, outputPath, manifestPath, requireWhoComponent = false }) {
  const exportDirectory = realpathSync(resolve(dist));
  if (!statSync(exportDirectory).isDirectory()) throw new Error("Expo export path is not a directory");
  const manifest = readManifest(exportDirectory, manifestPath ? resolve(manifestPath) : join(exportDirectory, "asset-manifest.json"));
  const index = readFileSync(join(exportDirectory, "index.html"), "utf8");
  const initialResources = parseInitialScripts(index);
  if (!initialResources.length) throw new Error("Export HTML has no initial JavaScript resources");

  const initial = initialResources.map(({ kind, url }) => {
    const relativePath = decodeLocalUrl(url, "initial script");
    return measure(exportDirectory, relativePath, kind);
  });
  const initialPaths = new Set(initial.map((entry) => entry.path));
  const deferred = collectExpoJavaScript(exportDirectory)
    .filter((file) => !initialPaths.has(`/app/${file}`))
    .map((file) => measure(exportDirectory, file, "deferred"));
  const runtime = deferred.filter((entry) => /\/whoRuntimeModule-[^/]+\.js$/.test(entry.path));
  const initialRuntime = initial.filter((entry) => /\/whoRuntimeModule-[^/]+\.js$/.test(entry.path));
  const assetsByPath = new Map(manifest.assets.map((asset) => [asset.path, asset]));
  const whoRequired = requireWhoComponent || /^expo-web-v/.test(manifest.release);
  const whoComponent = validateWhoComponent(manifest, {
    required: whoRequired,
    initialPaths,
    deferred,
    assetsByPath,
  });
  const initialInstrument = initial.filter((entry) => entry.contains_canonical_instrument_marker);
  const deferredInstrument = deferred.filter((entry) => entry.contains_canonical_instrument_marker);
  const initialTotals = totals(initial);
  const deferredTotals = totals(deferred);
  const total = totals([...initial, ...deferred]);
  const errors = [];
  if (initialTotals.raw_bytes > INITIAL_RAW_LIMIT) errors.push(`initial raw bytes ${initialTotals.raw_bytes} exceed ${INITIAL_RAW_LIMIT}`);
  if (initialTotals.gzip_bytes > INITIAL_GZIP_LIMIT) errors.push(`initial gzip bytes ${initialTotals.gzip_bytes} exceed ${INITIAL_GZIP_LIMIT}`);
  if (!runtime.length) errors.push("expected deferred whoRuntimeModule-*.js chunk was not found");
  if (initialRuntime.length) errors.push("whoRuntimeModule-*.js must not be an initial HTML script");
  if (initialInstrument.length) {
    errors.push(`canonical WHO instrument marker must remain deferred; found in initial ${initialInstrument.map((entry) => entry.path).join(", ")}`);
  }
  if (!initialInstrument.length && !deferredInstrument.length) {
    errors.push("canonical WHO instrument marker was not found in the emitted JavaScript graph");
  }
  const largest = [...initial, ...deferred]
    .sort((a, b) => b.raw_bytes - a.raw_bytes || a.path.localeCompare(b.path))
    .slice(0, 10);
  const report = {
    schema: 1,
    release: manifest.release,
    source_commit: manifest.source_commit,
    who_component: whoComponent,
    initial: { scripts: initial, ...initialTotals },
    deferred: { chunks: deferred, runtime_chunks: runtime, ...deferredTotals },
    canonical_instrument: {
      marker: CANONICAL_WHO_INSTRUMENT_MARKER,
      initial_chunks: initialInstrument.map((entry) => entry.path),
      deferred_chunks: deferredInstrument.map((entry) => entry.path),
    },
    total_javascript: total,
    largest_chunks: largest,
    gates: {
      initial_raw_bytes: INITIAL_RAW_LIMIT,
      initial_gzip_bytes: INITIAL_GZIP_LIMIT,
      passed: errors.length === 0,
      errors,
    },
  };
  if (outputPath) {
    mkdirSync(dirname(resolve(outputPath)), { recursive: true });
    writeFileSync(resolve(outputPath), `${JSON.stringify(report, null, 2)}\n`);
  }
  if (errors.length) {
    throw new Error(`Web bundle profile gate failed: ${errors.join("; ")}`);
  }
  return report;
}

function main() {
  const dist = process.argv[2];
  const outputPath = process.argv[3];
  if (!dist || !outputPath) {
    console.error("Usage: node scripts/profile-expo-web.mjs <expo-dist> <profile-json> [--require-who]");
    process.exitCode = 2;
    return;
  }
  try {
    const report = profileExpoWeb({ dist, outputPath, requireWhoComponent: process.argv[4] === "--require-who" });
    console.log(`Web bundle profile passed: initial ${report.initial.raw_bytes} raw / ${report.initial.gzip_bytes} gzip; deferred ${report.deferred.raw_bytes} raw / ${report.deferred.gzip_bytes} gzip; largest ${report.largest_chunks[0]?.path ?? "none"}`);
  } catch (error) {
    console.error(`Web bundle profile failed: ${error.message}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main();
