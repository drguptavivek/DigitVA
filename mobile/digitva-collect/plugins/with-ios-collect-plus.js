const path = require("node:path");
const { withDangerousMod, withPodfile } = require("@expo/config-plugins");
const { MODULE_NAME, SMARTVA_MODULE_NAME, plusBuildRequested } = require("./with-android-collect-plus");

/**
 * The iOS side of "DigitVA Collect Plus" (APP_VARIANT=plus; plugins/with-android-collect-plus.js is the Android one).
 * Plus stages the engines from private/ into the local modules before pod install: the ICD-11 xcframework and its
 * WHO data (`modules/digitva-icd11/ios/Engine`) and the SmartVA xcframework (`modules/digitva-smartva/ios/Engine`).
 * The plain build excludes both modules from autolinking, so its app carries no engine, data or module code.
 *
 * DIGITVA_IOS_SKIP_ICD11=1 builds Plus with SmartVA only: the ICD-11 module is excluded as in the plain build and
 * nothing is staged for it. CI uses it (.github/workflows/ios-build.yml), since no iOS ICD-11 engine is published.
 */
const PODFILE_MARKER = "# DigitVA Collect Plus: engine modules are plus-only";
const EXCLUSION = /^([ \t]*)# DigitVA Collect Plus: engine modules are plus-only\n[ \t]*use_expo_modules!\(exclude: \[[^\]]*\]\)[ \t]*$/m;

function icd11Skipped(env = process.env) {
  return env.DIGITVA_IOS_SKIP_ICD11 === "1";
}

/** The engine modules this build keeps out of autolinking: both for plain, ICD-11 for a SmartVA-only Plus, else none. */
function excludedModules(env = process.env) {
  if (!plusBuildRequested(env)) return [MODULE_NAME, SMARTVA_MODULE_NAME];
  return icd11Skipped(env) ? [MODULE_NAME] : [];
}

/**
 * Points the Podfile's `use_expo_modules!` at [modules]: `exclude:` with them, or the bare call when there are none.
 * Prebuild without --clean keeps the Podfile, so an exclusion an earlier build wrote is rewritten, never inherited
 * (a full Plus after a plain prebuild would otherwise lose both engines).
 */
function patchPodfile(contents, modules) {
  if (typeof contents !== "string") throw new Error("iOS Podfile contents must be a string");
  const call = (indent) =>
    modules.length === 0
      ? `${indent}use_expo_modules!`
      : `${indent}${PODFILE_MARKER}\n${indent}use_expo_modules!(exclude: [${modules.map((name) => JSON.stringify(name)).join(", ")}])`;
  if (contents.includes(PODFILE_MARKER)) {
    if (!EXCLUSION.test(contents)) throw new Error("Unsupported iOS Podfile: existing Plus exclusion is missing");
    return contents.replace(EXCLUSION, (_, indent) => call(indent));
  }
  if (modules.length === 0) return contents;
  const bare = /^([ \t]*)use_expo_modules!(?:\(\s*\))?[ \t]*$/m;
  if (!bare.test(contents)) throw new Error("Unsupported iOS Podfile: no bare use_expo_modules! call");
  return contents.replace(bare, (_, indent) => call(indent));
}

/** Plain build's Podfile: both engine modules out of autolinking. */
const patchPlainPodfile = (contents) => patchPodfile(contents, [MODULE_NAME, SMARTVA_MODULE_NAME]);

module.exports = function withIosCollectPlus(config) {
  const excluded = excludedModules();
  config = withPodfile(config, (config) => {
    config.modResults.contents = patchPodfile(config.modResults.contents, excluded);
    return config;
  });
  if (!plusBuildRequested()) return config;
  return withDangerousMod(config, [
    "ios",
    (config) => {
      const modules = path.join(config.modRequest.projectRoot, "modules");
      if (!icd11Skipped()) require(path.join(modules, MODULE_NAME, "scripts", "stage-engine")).stageEngineIos();
      require(path.join(modules, SMARTVA_MODULE_NAME, "scripts", "stage-engine")).stageSmartvaIos();
      return config;
    },
  ]);
};

module.exports.patchPlainPodfile = patchPlainPodfile;
module.exports.patchPodfile = patchPodfile;
module.exports.excludedModules = excludedModules;
