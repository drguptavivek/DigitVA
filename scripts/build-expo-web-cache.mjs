/** Build a deterministic public-asset manifest and worker after the CI-only Expo export. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const templates = join(dirname(fileURLToPath(import.meta.url)), "expo-web-cache");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const WHO_PACKAGE_NAME = "@drguptavivek/who-2022-va";
const WHO_BUILD_KEYS = [
  "schema", "release", "package_name", "package_version", "source_commit",
  "artifact_name", "artifact_sha256", "package_json_sha256", "dist_sha256", "files",
];
const WHO_FILE_KEYS = ["path", "size", "sha256"];
const SEMVER = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const SHA256 = /^[a-f0-9]{64}$/;
const SOURCE_COMMIT = /^[a-f0-9]{40}$/;
const SAFE_COMPONENT = /^[A-Za-z0-9][A-Za-z0-9._@()+-]*$/;

function exactKeys(value, expected, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || JSON.stringify(Object.keys(value).sort()) !== JSON.stringify([...expected].sort())) {
    throw new Error(`${label} has an unexpected schema`);
  }
}

function validateRelativeFilePath(value, label) {
  if (typeof value !== "string" || !value || value.startsWith("/") || value.includes("\\") || value.includes("\0")) {
    throw new Error(`${label} is unsafe`);
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === ".." || part.startsWith(".") || !SAFE_COMPONENT.test(part))) {
    throw new Error(`${label} is unsafe`);
  }
}

function validateWhoBuildMetadata(metadata, release, sourceCommit) {
  if (metadata === undefined) return undefined;
  exactKeys(metadata, WHO_BUILD_KEYS, "WHO build metadata");
  if (metadata.schema !== 1) throw new Error(`Unsupported WHO build schema: ${metadata.schema}`);
  if (metadata.release !== release) throw new Error(`WHO build release mismatch: expected ${release}, got ${metadata.release}`);
  if (metadata.package_name !== WHO_PACKAGE_NAME) throw new Error(`WHO package_name must be ${WHO_PACKAGE_NAME}`);
  if (typeof metadata.package_version !== "string" || !SEMVER.test(metadata.package_version)) {
    throw new Error(`WHO package_version is not valid semver: ${metadata.package_version}`);
  }
  if (metadata.source_commit !== sourceCommit) throw new Error(`WHO source commit mismatch: expected ${sourceCommit}, got ${metadata.source_commit}`);
  if (metadata.artifact_name !== `${release}-who-package.tgz`) throw new Error("WHO artifact_name is invalid");
  for (const field of ["artifact_sha256", "package_json_sha256", "dist_sha256"]) {
    if (typeof metadata[field] !== "string" || !SHA256.test(metadata[field])) throw new Error(`WHO ${field} is invalid`);
  }
  if (!Array.isArray(metadata.files) || metadata.files.length === 0 || metadata.files.length > 4096) throw new Error("WHO files is invalid");
  let previousPath = "";
  let total = 0;
  for (const file of metadata.files) {
    exactKeys(file, WHO_FILE_KEYS, "WHO file entry");
    validateRelativeFilePath(file.path, "WHO file path");
    if (file.path.localeCompare(previousPath) <= 0) throw new Error("WHO files must be sorted and unique");
    previousPath = file.path;
    if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > 32 * 1024 * 1024) {
      throw new Error(`WHO file size is invalid: ${file.path}`);
    }
    if (typeof file.sha256 !== "string" || !SHA256.test(file.sha256)) throw new Error(`WHO file sha256 is invalid: ${file.path}`);
    total += file.size;
  }
  if (total > 100 * 1024 * 1024) throw new Error("WHO dist exceeds size limit");
  if (sha256(JSON.stringify(metadata.files)) !== metadata.dist_sha256) throw new Error("WHO dist_sha256 does not match files");
  return {
    package_name: metadata.package_name,
    package_version: metadata.package_version,
    source_commit: metadata.source_commit,
    artifact_sha256: metadata.artifact_sha256,
    dist_sha256: metadata.dist_sha256,
  };
}

/** Refuse links, hidden files and oversized exports; include only public runtime asset directories. */
export function buildAssetCache(dist, release, sourceCommit, whoBuildMetadata) {
  if (!/^[a-zA-Z0-9._-]{1,100}$/.test(release) || !/^[a-f0-9]{40}$/.test(sourceCommit)) {
    throw new Error("Invalid release identity");
  }
  const whoComponent = validateWhoBuildMetadata(whoBuildMetadata, release, sourceCommit);
  const assets = [];
  let total = 0;
  function collect(relative) {
    const directory = join(dist, relative);
    if (lstatSync(directory).isSymbolicLink()) throw new Error("Symlink in export");
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : 1)) {
      if (entry.name.startsWith(".") || !/^[a-zA-Z0-9_.@()-]+$/.test(entry.name)) throw new Error("Unsafe asset name");
      const child = `${relative}/${entry.name}`;
      if (entry.isSymbolicLink()) throw new Error("Symlink in export");
      if (entry.isDirectory()) { collect(child); continue; }
      if (!entry.isFile() || entry.name.endsWith(".map")) continue;
      const size = lstatSync(join(dist, child)).size;
      total += size;
      if (assets.length >= 4096 || size > 32 * 1024 * 1024 || total > 100 * 1024 * 1024) throw new Error("Oversized public export");
      assets.push({
        path: `/app/${child}`, size,
        sha256: sha256(readFileSync(join(dist, child))),
        cacheable: /[.-][0-9a-f]{32,64}\./.test(entry.name),
      });
    }
  }
  collect("_expo");
  if (existsSync(join(dist, "assets"))) collect("assets");
  if (!assets.length) throw new Error("Export has no public assets");
  // WHO is loaded by the web runtime loader, so it is not an HTML entrypoint.
  // Keep its hashed chunk and any hashed JS chunks it names in a separate group;
  // the service worker can warm this group without downloading coding, login or
  // unrelated public assets. Metro may split the runtime into nested chunks, so
  // follow references until the closure stops changing.
  const byBasename = new Map(assets.map((asset) => [asset.path.split("/").at(-1), asset]));
  const interviewRuntime = assets
    .filter((asset) => asset.cacheable && /\/whoRuntimeModule-[^/]+\.js$/i.test(asset.path))
    .map((asset) => asset.path);
  const queued = [...interviewRuntime];
  const seen = new Set(interviewRuntime);
  while (queued.length) {
    const current = queued.shift();
    if (!current) continue;
    const file = join(dist, current.slice("/app/".length));
    if (!file.endsWith(".js")) continue;
    const source = readFileSync(file, "utf8");
    const references = source.match(/[A-Za-z0-9_@()\-]+-[0-9a-f]{32,64}\.js/g) ?? [];
    for (const basename of references) {
      const asset = byBasename.get(basename);
      if (!asset || !asset.cacheable || seen.has(asset.path)) continue;
      seen.add(asset.path);
      queued.push(asset.path);
      interviewRuntime.push(asset.path);
    }
  }
  interviewRuntime.sort();
  const identity = {
    schema: 2,
    release,
    source_commit: sourceCommit,
    assets,
    groups: { interviewRuntime },
  };
  if (whoComponent) identity.components = { who: whoComponent };
  const manifest = { ...identity, manifest_sha256: sha256(JSON.stringify(identity)) };
  const json = JSON.stringify(manifest);
  writeFileSync(join(dist, "asset-manifest.json"), `${json}\n`);
  writeFileSync(join(dist, "asset-worker.js"), readFileSync(join(templates, "worker.js"), "utf8").replace("__DIGITVA_ASSET_MANIFEST__", json));
  writeFileSync(join(dist, "cache-register.js"), readFileSync(join(templates, "register.js"), "utf8").replace("__DIGITVA_RELEASE__", JSON.stringify(release)));
  const indexPath = join(dist, "index.html");
  const index = readFileSync(indexPath, "utf8");
  if (!index.includes("</head>")) throw new Error("Export index has no head");
  const tag = '<script src="/app/cache-register.js" defer></script>';
  writeFileSync(indexPath, index.includes(tag) ? index : index.replace("</head>", `${tag}</head>`));
  return manifest;
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const metadataPath = process.argv[5];
  let metadata;
  if (metadataPath) {
    try {
      metadata = JSON.parse(readFileSync(resolve(metadataPath), "utf8"));
    } catch (error) {
      console.error(`Invalid WHO metadata JSON: ${error.message}`);
      process.exitCode = 1;
    }
  }
  if (process.exitCode !== 1) buildAssetCache(resolve(process.argv[2]), process.argv[3], process.argv[4], metadata);
}
