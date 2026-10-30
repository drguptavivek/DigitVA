#!/usr/bin/env node
/**
 * Stage the offline ICD-11 engine into this module for a Collect Plus build (APP_VARIANT=plus). The engine and its
 * data come from one of two sources, in this order:
 *   1. DIGITVA_ICD11_ENGINE_ARCHIVE: the icd11-engine-<version>.tar.gz that scripts/package-icd11-engine.sh made (CI
 *      downloads and checksums the public release asset, then sets this). Extracted to a temp dir, staged, removed.
 *   2. DIGITVA_ICD11_SPIKE_DIR, else the owner's private spike folder (private/icd11-offline-spike, git-ignored).
 * Prefer the archive for local builds. The shim refuses an engine library without digitva_icd11_call (engines before
 * 2026.10.29, such as an old private spike): the app then reports the engine unavailable. A spike folder works only with a
 * digitva_icd11.so from engine-src/build.sh of this checkout.
 * Both have the same layout, and engineFiles() lists the files the app ships from it:
 *   bridge-aot/pub-bionic/digitva_icd11.so -> android/src/main/jniLibs/arm64-v8a/libdigitva_icd11.so
 *   bundle_min/**                          -> android/src/main/assets/digitva-icd11/bundle/**.bin
 *   data/<the files below>                 -> android/src/main/assets/digitva-icd11/data/**.bin
 * Every asset gets a ".bin" suffix because AAPT expands ".gz" assets on packaging; EngineData.kt strips it on copy.
 * Data is the minimum the engine needs (checked on a phone): the ICD-11 release .pbf.gz, the search index .pbf.zip
 * (the engine unzips it and builds its own annex on first init), and the extracted DORIS rule files. The 30 MB
 * prebuilt ".annex", the unzipped ".pbf"/".annexu", DORIS's own .zip and DORIS's generated log.txt are not needed.
 *
 * The WHO-supplied files (the ones the engine's loaders fetch from WHO) are listed in assets/digitva-icd11/
 * who-files.json with their size and sha256. The app verifies the staged copies against it and restores them when
 * missing (EngineData.kt), so the manifest is written from the staged copies, never from the spike's files by hand.
 *
 * CLI: `node stage-engine.js` stages; `--list <spike>` prints engineFiles(); `--spike` prints the spike folder found.
 */
const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const SPIKE = ["private", "icd11-offline-spike"];
const ENGINE_LIB = path.join("bridge-aot", "pub-bionic", "digitva_icd11.so");
const DATA_FILES = [
  "icd11_2026-01-17_release-icf-mms_en.pbf.gz",
  "ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip",
];
const DORIS_DIR = "DORIS_v2.1_1.2.0";
// DORIS's zip is fetched by the engine, and its log.txt is written by the engine: neither is shipped.
const DORIS_SKIP = new Set(["DORIS_v2.1_1.2.0.zip", "log.txt"]);
const MISSING_ENGINE =
  "Collect Plus (APP_VARIANT=plus) needs the offline ICD-11 engine: set DIGITVA_ICD11_ENGINE_ARCHIVE to the " +
  "icd11-engine-<version>.tar.gz of the release the CI workflow pins (preferred), or provide the folder " +
  "private/icd11-offline-spike/ (bridge-aot/pub-bionic/digitva_icd11.so, bundle_min/, data/), which is not in git, or set " +
  "DIGITVA_ICD11_SPIKE_DIR to such a folder. The library must export digitva_icd11_call (built by engine-src/build.sh of 2026.10.29 or later).";

/** The spike folder: $DIGITVA_ICD11_SPIKE_DIR, else the first ancestor of this module that has private/icd11-offline-spike (a worktree finds the main checkout's). */
function findSpike(env = process.env, from = MODULE_DIR) {
  const candidates = [];
  if (env.DIGITVA_ICD11_SPIKE_DIR) candidates.push(env.DIGITVA_ICD11_SPIKE_DIR);
  for (let dir = from; ; dir = path.dirname(dir)) {
    candidates.push(path.join(dir, ...SPIKE));
    if (dir === path.dirname(dir)) break;
  }
  return candidates.find((dir) => fs.existsSync(path.join(dir, ENGINE_LIB)));
}

/**
 * The files the app ships, relative to the engine source folder, sorted. scripts/package-icd11-engine.sh archives
 * exactly this list (`--list`), so an archive stages the same files as the spike folder does.
 */
function engineFiles(source) {
  const bundle = listFiles(path.join(source, "bundle_min")).map((file) => path.join("bundle_min", file));
  const data = DATA_FILES.map((file) => path.join("data", file));
  const doris = listFiles(path.join(source, "data", DORIS_DIR), DORIS_SKIP).map((file) => path.join("data", DORIS_DIR, file));
  return [ENGINE_LIB, ...bundle, ...data, ...doris].sort();
}

/** True for a staged engine-relative path (bundle/..., data/...) that the engine fetches from WHO. */
function isWhoFile(rel) {
  return rel === path.join("bundle", "Data", "languageResources.txt") || rel.startsWith(`data${path.sep}`);
}

/**
 * Runs [use] with the engine source folder: the extracted archive when DIGITVA_ICD11_ENGINE_ARCHIVE is set (its temp dir
 * is removed afterwards), else the spike folder. Throws MISSING_ENGINE when neither is there.
 */
function withEngineSource(env, moduleDir, use) {
  const archive = env.DIGITVA_ICD11_ENGINE_ARCHIVE;
  if (!archive) {
    const spike = findSpike(env, moduleDir);
    if (!spike) throw new Error(MISSING_ENGINE);
    return use(spike);
  }
  if (!fs.existsSync(archive)) throw new Error(`Collect Plus: DIGITVA_ICD11_ENGINE_ARCHIVE does not exist: ${archive}`);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "digitva-icd11-engine-"));
  try {
    execFileSync("tar", ["-xzf", path.resolve(archive), "-C", dir]);
    if (!fs.existsSync(path.join(dir, ENGINE_LIB))) {
      throw new Error(`Collect Plus: ${archive} does not contain the offline ICD-11 engine`);
    }
    return use(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function copyIfChanged(from, to) {
  if (!fs.existsSync(from)) throw new Error(`Collect Plus: engine file missing: ${from}`);
  const size = fs.statSync(from).size;
  if (fs.existsSync(to) && fs.statSync(to).size === size) return;
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
}

function listFiles(dir, skip = new Set()) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (skip.has(entry.name)) return [];
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? listFiles(full, skip).map((file) => path.join(entry.name, file)) : [entry.name];
  });
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function stageEngine({ moduleDir = MODULE_DIR, env = process.env } = {}) {
  return withEngineSource(env, moduleDir, (source) => {
    const main = path.join(moduleDir, "android", "src", "main");
    const assets = path.join(main, "assets", "digitva-icd11");
    const who = [];
    for (const file of engineFiles(source)) {
      const from = path.join(source, file);
      if (file === ENGINE_LIB) {
        copyIfChanged(from, path.join(main, "jniLibs", "arm64-v8a", "libdigitva_icd11.so"));
        continue;
      }
      // Engine-relative path (bundle/..., data/...); the staged asset is that path with a ".bin" suffix.
      const rel = file.startsWith(`bundle_min${path.sep}`) ? path.join("bundle", path.relative("bundle_min", file)) : file;
      copyIfChanged(from, path.join(assets, `${rel}.bin`));
      if (isWhoFile(rel)) who.push({ path: rel, size: fs.statSync(from).size, sha256: sha256(from) });
    }
    fs.writeFileSync(path.join(assets, "who-files.json"), `${JSON.stringify(who, null, 2)}\n`);
    return { source, assets, who };
  });
}

module.exports = { stageEngine, findSpike, engineFiles };

if (require.main === module) {
  const [flag, arg] = process.argv.slice(2);
  try {
    if (flag === "--list") {
      if (!arg) throw new Error("usage: stage-engine.js --list <spike-or-engine-folder>");
      for (const file of engineFiles(arg)) console.log(file);
    } else if (flag === "--spike") {
      const spike = findSpike();
      if (!spike) throw new Error(MISSING_ENGINE);
      console.log(spike);
    } else {
      const { source } = stageEngine();
      console.log(`Collect Plus: engine staged from ${source}`);
    }
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
