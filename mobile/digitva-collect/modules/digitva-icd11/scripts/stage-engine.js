#!/usr/bin/env node
/**
 * Stage the offline ICD-11 engine into this module for a Collect Plus build (APP_VARIANT=plus). The engine and its
 * data come from the owner's private spike folder (private/icd11-offline-spike, git-ignored, never committed):
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
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const SPIKE = ["private", "icd11-offline-spike"];
const DATA_FILES = [
  "icd11_2026-01-17_release-icf-mms_en.pbf.gz",
  "ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip",
];
const DORIS_DIR = "DORIS_v2.1_1.2.0";
// DORIS's zip is fetched by the engine, and its log.txt is written by the engine: neither is shipped.
const DORIS_SKIP = new Set(["DORIS_v2.1_1.2.0.zip", "log.txt"]);

/** The spike folder: $DIGITVA_ICD11_SPIKE_DIR, else the first ancestor of this module that has private/icd11-offline-spike (a worktree finds the main checkout's). */
function findSpike(env = process.env, from = MODULE_DIR) {
  const candidates = [];
  if (env.DIGITVA_ICD11_SPIKE_DIR) candidates.push(env.DIGITVA_ICD11_SPIKE_DIR);
  for (let dir = from; ; dir = path.dirname(dir)) {
    candidates.push(path.join(dir, ...SPIKE));
    if (dir === path.dirname(dir)) break;
  }
  return candidates.find((dir) => fs.existsSync(path.join(dir, "bridge-aot", "pub-bionic", "digitva_icd11.so")));
}

function copyIfChanged(from, to) {
  if (!fs.existsSync(from)) throw new Error(`Collect Plus: engine file missing in private/: ${from}`);
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
  const spike = findSpike(env, moduleDir);
  if (!spike) {
    throw new Error(
      "Collect Plus (APP_VARIANT=plus) needs the offline ICD-11 engine in private/icd11-offline-spike/ " +
        "(bridge-aot/pub-bionic/digitva_icd11.so, bundle_min/, data/), which is not in git. Run this build from a " +
        "checkout that has private/, or set DIGITVA_ICD11_SPIKE_DIR to the spike folder."
    );
  }
  const main = path.join(moduleDir, "android", "src", "main");
  copyIfChanged(
    path.join(spike, "bridge-aot", "pub-bionic", "digitva_icd11.so"),
    path.join(main, "jniLibs", "arm64-v8a", "libdigitva_icd11.so")
  );
  const assets = path.join(main, "assets", "digitva-icd11");
  // Relative paths under the engine root (bundle/, data/) of the WHO-supplied files that ship.
  const who = [];
  const stageWho = (from, rel) => {
    copyIfChanged(from, path.join(assets, `${rel}.bin`));
    who.push({ path: rel, size: fs.statSync(from).size, sha256: sha256(from) });
  };
  const WHO_BUNDLE = path.join("Data", "languageResources.txt");
  for (const file of listFiles(path.join(spike, "bundle_min"))) {
    if (file === WHO_BUNDLE) continue;
    copyIfChanged(path.join(spike, "bundle_min", file), path.join(assets, "bundle", `${file}.bin`));
  }
  stageWho(path.join(spike, "bundle_min", WHO_BUNDLE), `bundle/${WHO_BUNDLE}`);
  for (const file of DATA_FILES) stageWho(path.join(spike, "data", file), `data/${file}`);
  for (const file of listFiles(path.join(spike, "data", DORIS_DIR), DORIS_SKIP)) {
    stageWho(path.join(spike, "data", DORIS_DIR, file), `data/${DORIS_DIR}/${file}`);
  }
  fs.writeFileSync(path.join(assets, "who-files.json"), `${JSON.stringify(who, null, 2)}\n`);
  return { spike, assets, who };
}

module.exports = { stageEngine, findSpike };

if (require.main === module) {
  try {
    const { spike } = stageEngine();
    console.log(`Collect Plus: engine staged from ${spike}`);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
