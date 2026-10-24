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
 * prebuilt ".annex", the unzipped ".pbf"/".annexu" and DORIS's own .zip are not needed.
 */
const fs = require("node:fs");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const SPIKE = ["private", "icd11-offline-spike"];
const DATA_FILES = [
  "icd11_2026-01-17_release-icf-mms_en.pbf.gz",
  "ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip",
];
const DORIS_DIR = "DORIS_v2.1_1.2.0";
const DORIS_SKIP = new Set(["DORIS_v2.1_1.2.0.zip"]);

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
  for (const file of listFiles(path.join(spike, "bundle_min"))) {
    copyIfChanged(path.join(spike, "bundle_min", file), path.join(assets, "bundle", `${file}.bin`));
  }
  for (const file of DATA_FILES) {
    copyIfChanged(path.join(spike, "data", file), path.join(assets, "data", `${file}.bin`));
  }
  for (const file of listFiles(path.join(spike, "data", DORIS_DIR), DORIS_SKIP)) {
    copyIfChanged(path.join(spike, "data", DORIS_DIR, file), path.join(assets, "data", DORIS_DIR, `${file}.bin`));
  }
  return { spike, assets };
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
