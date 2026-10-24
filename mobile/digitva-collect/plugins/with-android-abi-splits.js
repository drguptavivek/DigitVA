const { withAppBuildGradle, withGradleProperties } = require("@expo/config-plugins");

const { plusBuildRequested } = require("./with-android-collect-plus");
const { releaseBuildRequested } = require("./with-android-release-signing");

/**
 * Release builds ship one APK per ARM ABI (no universal APK), so a phone
 * downloads only its own native libraries. Each APK's versionCode is
 * `base * 10 + ABI digit` (armeabi-v7a 1, arm64-v8a 2): distinct per ABI and
 * still increasing with the base from app.config.js. Debug prebuilds are left
 * unchanged (one app-debug.apk).
 */
const RELEASE_ABIS = ["armeabi-v7a", "arm64-v8a"];
const ABIS_PLUS = ["arm64-v8a"];
const MARKER = "// DigitVA release ABI splits";

// Collect Plus ships arm64 only; the ABI digit still comes from RELEASE_ABIS so it stays 2.
const abiSplitsBlock = (abis) => `
${MARKER}: one APK per ABI, versionCode = base * 10 + ABI digit.
android {
    splits {
        abi {
            enable true
            reset()
            include ${abis.map((abi) => `"${abi}"`).join(", ")}
            universalApk false
        }
    }
}

androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.outputs.each { output ->
            def abi = output.filters.find { it.filterType.name() == "ABI" }?.identifier
            def abiDigit = [${RELEASE_ABIS.map((abi, index) => `"${abi}": ${index + 1}`).join(", ")}][abi]
            if (abiDigit == null) {
                throw new GradleException("DigitVA release output has no supported ABI: " + abi)
            }
            output.versionCode.set(output.versionCode.get() * 10 + abiDigit)
        }
    }
}
`;

function patchAndroidAbiSplits(contents, abis = RELEASE_ABIS) {
  if (typeof contents !== "string") throw new Error("Android Gradle contents must be a string");
  if (contents.includes(MARKER)) return contents;
  return `${contents.trimEnd()}\n${abiSplitsBlock(abis)}`;
}

module.exports = function withAndroidAbiSplits(config) {
  const plus = plusBuildRequested();
  if (!releaseBuildRequested() && !plus) return config;
  const abis = plus ? ABIS_PLUS : RELEASE_ABIS;
  config = withGradleProperties(config, (config) => {
    // Build only the shipped ABIs' native code.
    config.modResults = config.modResults.filter(
      (item) => !(item.type === "property" && item.key === "reactNativeArchitectures")
    );
    config.modResults.push({ type: "property", key: "reactNativeArchitectures", value: abis.join(",") });
    return config;
  });
  return withAppBuildGradle(config, (config) => {
    if (config.modResults.language !== "groovy") {
      throw new Error("withAndroidAbiSplits requires an app/build.gradle Groovy template");
    }
    config.modResults.contents = patchAndroidAbiSplits(config.modResults.contents, abis);
    return config;
  });
};

module.exports.patchAndroidAbiSplits = patchAndroidAbiSplits;
module.exports.RELEASE_ABIS = RELEASE_ABIS;
