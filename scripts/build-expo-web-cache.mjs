/** Build a deterministic public-asset manifest and worker after the CI-only Expo export. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const templates = join(dirname(fileURLToPath(import.meta.url)), "expo-web-cache");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

/** Refuse links, hidden files and oversized exports; include only public runtime asset directories. */
export function buildAssetCache(dist, release, sourceCommit) {
  if (!/^[a-zA-Z0-9._-]{1,100}$/.test(release) || !/^[a-f0-9]{40}$/.test(sourceCommit)) {
    throw new Error("Invalid release identity");
  }
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
  buildAssetCache(resolve(process.argv[2]), process.argv[3], process.argv[4]);
}
