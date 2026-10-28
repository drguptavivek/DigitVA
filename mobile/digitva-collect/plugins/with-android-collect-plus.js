const path = require("node:path");
const {
  withAndroidManifest,
  withAppBuildGradle,
  withDangerousMod,
  withGradleProperties,
  withSettingsGradle,
} = require("@expo/config-plugins");

/**
 * "DigitVA Collect Plus" (APP_VARIANT=plus): the experimental, adb-only build that runs the offline ICD-11 and SmartVA engines
 * (docs/policy/field-data-collection.md). Plus gets arm64 only (plugins/with-android-abi-splits.js), extracted native libraries (the engine is dlopen'ed
 * by path from nativeLibraryDir) and the engine staged from private/ into the local module
 * `modules/digitva-icd11` and `modules/digitva-smartva`. The plain build excludes both from autolinking, so its APK
 * carries no engine assets or module code.
 */
const MODULE_NAME = "digitva-icd11";
const SMARTVA_MODULE_NAME = "digitva-smartva";
const ENGINE_LIB = "libdigitva_icd11.so";
const SETTINGS_MARKER = "// DigitVA Collect Plus: engine module is plus-only";
const GRADLE_MARKER = "// DigitVA Collect Plus: extracted native libraries";
const JVM_ARGS_KEY = "org.gradle.jvmargs";
// The engine's native build and its ~130 MB .so need more heap than the Gradle default; plain builds keep the default.
const PLUS_JVM_ARGS = "-Xmx6144m -XX:MaxMetaspaceSize=512m";

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

/** Plus only: sets org.gradle.jvmargs, replacing an existing entry in place and appending one otherwise. */
function patchPlusGradleProperties(properties) {
  if (!Array.isArray(properties)) throw new Error("Android gradle.properties contents must be an array");
  const entry = { type: "property", key: JVM_ARGS_KEY, value: PLUS_JVM_ARGS };
  const index = properties.findIndex((item) => item.type === "property" && item.key === JVM_ARGS_KEY);
  if (index === -1) return [...properties, entry];
  return properties.map((item, i) => (i === index ? entry : item));
}

/** Plain build: keep the plus-only module out of Expo autolinking. */
function patchPlainSettings(contents) {
  if (typeof contents !== "string") throw new Error("Android settings.gradle contents must be a string");
  if (contents.includes(SETTINGS_MARKER)) {
    const exclusion = contents.match(/expoAutolinking\.exclude\s*=\s*\[[^\]]*\]/)?.[0];
    if (!exclusion) throw new Error("Unsupported Android settings.gradle: existing Plus exclusion is missing");
    if (exclusion.includes(`"${SMARTVA_MODULE_NAME}"`)) return contents;
    return contents.replace(exclusion, exclusion.replace(/\]$/, `, "${SMARTVA_MODULE_NAME}"]`));
  }
  const call = "expoAutolinking.useExpoModules()";
  if (!contents.includes(call)) throw new Error("Unsupported Android settings.gradle: no useExpoModules() call");
  return contents.replace(call, `${SETTINGS_MARKER}\nexpoAutolinking.exclude = ["${MODULE_NAME}", "${SMARTVA_MODULE_NAME}"]\n${call}`);
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
  config = withGradleProperties(config, (config) => {
    config.modResults = patchPlusGradleProperties(config.modResults);
    return config;
  });
  config = withAppBuildGradle(config, (config) => {
    if (config.modResults.language !== "groovy") {
      throw new Error("withAndroidCollectPlus requires an app/build.gradle Groovy template");
    }
    config.modResults.contents = patchPlusGradle(config.modResults.contents);
    return config;
  });
  // Stage private Plus binaries; fail clearly when either source is absent.
  return withDangerousMod(config, [
    "android",
    (config) => {
      const { stageEngine } = require(path.join(config.modRequest.projectRoot, "modules", MODULE_NAME, "scripts", "stage-engine"));
      stageEngine();
      const { stageSmartva } = require(path.join(config.modRequest.projectRoot, "modules", SMARTVA_MODULE_NAME, "scripts", "stage-engine"));
      stageSmartva();
      return config;
    },
  ]);
};

module.exports.plusBuildRequested = plusBuildRequested;
module.exports.patchPlusGradle = patchPlusGradle;
module.exports.patchPlusGradleProperties = patchPlusGradleProperties;
module.exports.patchPlainSettings = patchPlainSettings;
module.exports.addProfileable = addProfileable;
module.exports.MODULE_NAME = MODULE_NAME;
module.exports.SMARTVA_MODULE_NAME = SMARTVA_MODULE_NAME;
