const path = require("node:path");
const {
  withAndroidManifest,
  withAppBuildGradle,
  withDangerousMod,
  withSettingsGradle,
} = require("@expo/config-plugins");

/**
 * "DigitVA Collect Plus" (APP_VARIANT=plus): the experimental, adb-only build that runs the offline ICD-11 engine
 * (docs/policy/field-data-collection.md). Plus gets arm64 only (plugins/with-android-abi-splits.js), extracted native libraries (the engine is dlopen'ed
 * by path from nativeLibraryDir) and the engine staged from private/ into the local module
 * `modules/digitva-icd11`. The plain build gets one settings.gradle line that keeps that module out of
 * autolinking, so the plain APK carries no engine, no engine assets and no module code.
 */
const MODULE_NAME = "digitva-icd11";
const ENGINE_LIB = "libdigitva_icd11.so";
const SETTINGS_MARKER = "// DigitVA Collect Plus: engine module is plus-only";
const GRADLE_MARKER = "// DigitVA Collect Plus: extracted native libraries";

function plusBuildRequested(env = process.env) {
  return env.APP_VARIANT === "plus";
}

/**
 * Plus only: a profileable release lets `adb shell perfetto` (scripts/android-trace.sh) record the app and the
 * :icd11 engine process, with the icd11.* trace sections. Not added to the plain build, which stays unprofileable.
 */
function addProfileable(application) {
  if (!application || typeof application !== "object") throw new Error("Plus build: AndroidManifest application must be an object");
  application.profileable = [{ $: { "android:shell": "true" } }];
  return application;
}

const PLUS_GRADLE_BLOCK = `
${GRADLE_MARKER}: the engine .so is dlopen'ed from nativeLibraryDir and must stay unstripped.
android {
    packaging {
        jniLibs {
            useLegacyPackaging = true
            keepDebugSymbols += ["**/${ENGINE_LIB}"]
        }
    }
}
`;

function patchPlusGradle(contents) {
  if (typeof contents !== "string") throw new Error("Android Gradle contents must be a string");
  if (contents.includes(GRADLE_MARKER)) return contents;
  return `${contents.trimEnd()}\n${PLUS_GRADLE_BLOCK}`;
}

/** Plain build: keep the plus-only module out of Expo autolinking. */
function patchPlainSettings(contents) {
  if (typeof contents !== "string") throw new Error("Android settings.gradle contents must be a string");
  if (contents.includes(SETTINGS_MARKER)) return contents;
  const call = "expoAutolinking.useExpoModules()";
  if (!contents.includes(call)) throw new Error("Unsupported Android settings.gradle: no useExpoModules() call");
  return contents.replace(call, `${SETTINGS_MARKER}\nexpoAutolinking.exclude = ["${MODULE_NAME}"]\n${call}`);
}

module.exports = function withAndroidCollectPlus(config) {
  if (!plusBuildRequested()) {
    return withSettingsGradle(config, (config) => {
      config.modResults.contents = patchPlainSettings(config.modResults.contents);
      return config;
    });
  }
  config = withAndroidManifest(config, (config) => {
    const application = config.modResults.manifest.application?.[0];
    if (!application) throw new Error("Plus build: AndroidManifest has no application element");
    application.$["android:extractNativeLibs"] = "true";
    addProfileable(application);
    return config;
  });
  config = withAppBuildGradle(config, (config) => {
    if (config.modResults.language !== "groovy") {
      throw new Error("withAndroidCollectPlus requires an app/build.gradle Groovy template");
    }
    config.modResults.contents = patchPlusGradle(config.modResults.contents);
    return config;
  });
  // Copies the engine out of private/ (never committed); throws a plain message when private/ is missing.
  return withDangerousMod(config, [
    "android",
    (config) => {
      const { stageEngine } = require(path.join(config.modRequest.projectRoot, "modules", MODULE_NAME, "scripts", "stage-engine"));
      stageEngine();
      return config;
    },
  ]);
};

module.exports.plusBuildRequested = plusBuildRequested;
module.exports.patchPlusGradle = patchPlusGradle;
module.exports.patchPlainSettings = patchPlainSettings;
module.exports.addProfileable = addProfileable;
module.exports.MODULE_NAME = MODULE_NAME;
