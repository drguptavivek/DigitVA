const path = require("node:path");
const { withDangerousMod, withPodfile } = require("@expo/config-plugins");

/**
 * The iOS twin of plugins/with-android-collect-plus.js. "DigitVA Collect Plus" (APP_VARIANT=plus) carries the offline
 * ICD-11 and SmartVA engines; the plain build must not link either module.
 *
 * Plain build: the generated Podfile's `use_expo_modules!` gets `exclude:` with both engine modules, the Podfile
 * counterpart of Android's `expoAutolinking.exclude` in settings.gradle (expo-modules-autolinking passes it on as
 * --exclude), so neither pod is installed and the app carries no engine code.
 *
 * Plus build: the engines are staged into the modules' ios/ folders before `pod install` (prebuild runs mods first),
 * and the podspecs vendor what they find:
 *   modules/digitva-smartva/scripts/stage-engine.js stageSmartvaIos  SmartvaRust.xcframework (scripts/build-smartva-ios.sh)
 *   modules/digitva-icd11/scripts/stage-engine.js   stageIcd11Ios    DigitvaIcd11Engine.xcframework + WHO data
 * A missing engine fails the prebuild with the staging script's message. DIGITVA_IOS_SKIP_ICD11=1 builds Plus with
 * SmartVA only: the ICD-11 module is then excluded like in the plain build (CI until an iOS engine is pinned, bead
 * digitva-nujw.4).
 */
const MODULE_NAME = "digitva-icd11";
const SMARTVA_MODULE_NAME = "digitva-smartva";
const PODFILE_MARKER = "# DigitVA Collect Plus: engine modules excluded from this build";
const USE_EXPO_MODULES = /^([ \t]*)use_expo_modules!(?:\(\s*\))?[ \t]*$/m;

function plusBuildRequested(env = process.env) {
  return env.APP_VARIANT === "plus";
}

function icd11Skipped(env = process.env) {
  return env.DIGITVA_IOS_SKIP_ICD11 === "1";
}

/** The engine modules this build keeps out of autolinking: both for plain, the ICD-11 one for a SmartVA-only Plus. */
function excludedModules(env = process.env) {
  if (!plusBuildRequested(env)) return [MODULE_NAME, SMARTVA_MODULE_NAME];
  return icd11Skipped(env) ? [MODULE_NAME] : [];
}

/**
 * Adds `exclude: [...]` to the Podfile's bare `use_expo_modules!` call, once. A Podfile already patched by this plugin is
 * rewritten to [modules]; one whose call already takes arguments is refused rather than guessed at.
 */
function patchPodfileExclude(contents, modules) {
  if (typeof contents !== "string") throw new Error("iOS Podfile contents must be a string");
  if (!Array.isArray(modules) || modules.length === 0) throw new Error("patchPodfileExclude needs at least one module");
  const list = modules.map((name) => JSON.stringify(name)).join(", ");
  const markerAt = contents.indexOf(PODFILE_MARKER);
  if (markerAt !== -1) {
    const patched = /^([ \t]*)use_expo_modules!\(exclude: \[[^\]]*\]\)[ \t]*$/m;
    if (!patched.test(contents)) throw new Error("Unsupported iOS Podfile: existing Plus exclusion is missing");
    return contents.replace(patched, (_line, indent) => `${indent}use_expo_modules!(exclude: [${list}])`);
  }
  const match = contents.match(USE_EXPO_MODULES);
  if (!match) throw new Error("Unsupported iOS Podfile: no bare use_expo_modules! call");
  const indent = match[1];
  return contents.replace(USE_EXPO_MODULES, `${indent}${PODFILE_MARKER}\n${indent}use_expo_modules!(exclude: [${list}])`);
}

/**
 * Undoes patchPodfileExclude: a full Plus build reuses a Podfile a plain prebuild patched (prebuild without --clean),
 * and must not inherit its exclusion. A Podfile without the marker is returned unchanged.
 */
function unpatchPodfileExclude(contents) {
  if (typeof contents !== "string") throw new Error("iOS Podfile contents must be a string");
  if (!contents.includes(PODFILE_MARKER)) return contents;
  const patched = /^([ \t]*)# DigitVA Collect Plus: engine modules excluded from this build\n[ \t]*use_expo_modules!\(exclude: \[[^\]]*\]\)[ \t]*$/m;
  if (!patched.test(contents)) throw new Error("Unsupported iOS Podfile: existing Plus exclusion is missing");
  return contents.replace(patched, (_block, indent) => `${indent}use_expo_modules!`);
}

/** Plus only: copies the private iOS engines into the modules. Throws the staging script's message when one is missing. */
function stageIosEngines(projectRoot, env = process.env) {
  const smartva = require(path.join(projectRoot, "modules", SMARTVA_MODULE_NAME, "scripts", "stage-engine"));
  const staged = { smartva: smartva.stageSmartvaIos() };
  if (!icd11Skipped(env)) {
    const icd11 = require(path.join(projectRoot, "modules", MODULE_NAME, "scripts", "stage-engine"));
    staged.icd11 = icd11.stageIcd11Ios({ env });
  }
  return staged;
}

module.exports = function withIosCollectPlus(config) {
  const excluded = excludedModules();
  config = withPodfile(config, (config) => {
    const contents = config.modResults.contents;
    config.modResults.contents =
      excluded.length > 0 ? patchPodfileExclude(contents, excluded) : unpatchPodfileExclude(contents);
    return config;
  });
  if (!plusBuildRequested()) return config;
  return withDangerousMod(config, [
    "ios",
    (config) => {
      stageIosEngines(config.modRequest.projectRoot);
      return config;
    },
  ]);
};

module.exports.plusBuildRequested = plusBuildRequested;
module.exports.icd11Skipped = icd11Skipped;
module.exports.excludedModules = excludedModules;
module.exports.patchPodfileExclude = patchPodfileExclude;
module.exports.unpatchPodfileExclude = unpatchPodfileExclude;
module.exports.stageIosEngines = stageIosEngines;
module.exports.MODULE_NAME = MODULE_NAME;
module.exports.SMARTVA_MODULE_NAME = SMARTVA_MODULE_NAME;
