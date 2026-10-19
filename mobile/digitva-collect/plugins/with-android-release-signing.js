const path = require("node:path");
const { withAppBuildGradle } = require("@expo/config-plugins");

const RELEASE_ENV_KEYS = [
  "ANDROID_RELEASE_STORE_FILE",
  "ANDROID_RELEASE_KEYSTORE_PASSWORD",
  "ANDROID_RELEASE_KEY_ALIAS",
  "ANDROID_RELEASE_KEY_PASSWORD",
];

function releaseBuildRequested(env = process.env) {
  return env.DIGITVA_ANDROID_RELEASE_BUILD === "1";
}

function validateReleaseSigningEnv(env = process.env) {
  if (!releaseBuildRequested(env)) return;
  const missing = RELEASE_ENV_KEYS.filter((key) => !String(env[key] || "").trim());
  if (missing.length) {
    throw new Error(
      `Android release signing requires ${RELEASE_ENV_KEYS.join(", ")} when DIGITVA_ANDROID_RELEASE_BUILD=1`
    );
  }
  if (!path.isAbsolute(String(env.ANDROID_RELEASE_STORE_FILE).trim())) {
    throw new Error("ANDROID_RELEASE_STORE_FILE must be an absolute path");
  }
}

function findBlock(contents, name, from = 0) {
  const expression = new RegExp(`\\b${name}\\s*\\{`, "g");
  expression.lastIndex = from;
  const match = expression.exec(contents);
  if (!match) return null;
  const open = contents.indexOf("{", match.index);
  let depth = 0;
  for (let index = open; index < contents.length; index += 1) {
    if (contents[index] === "{") depth += 1;
    if (contents[index] === "}") {
      depth -= 1;
      if (depth === 0) {
        return { start: match.index, open, end: index + 1, body: contents.slice(open + 1, index) };
      }
    }
  }
  return null;
}

function findOnlyBlock(contents, name) {
  const first = findBlock(contents, name);
  if (!first || findBlock(contents, name, first.end)) {
    throw new Error(`Unsupported Android Gradle template: expected exactly one ${name} block`);
  }
  return first;
}

const RELEASE_SIGNING_BLOCK = `
        release {
            // DigitVA release signing: credentials are read by Gradle at build time.
            def releaseStoreFile = System.getenv("ANDROID_RELEASE_STORE_FILE")
            def releaseKeystorePassword = System.getenv("ANDROID_RELEASE_KEYSTORE_PASSWORD")
            def releaseKeyAlias = System.getenv("ANDROID_RELEASE_KEY_ALIAS")
            def releaseKeyPassword = System.getenv("ANDROID_RELEASE_KEY_PASSWORD")
            def releaseSigningValues = [releaseStoreFile, releaseKeystorePassword, releaseKeyAlias, releaseKeyPassword]
            if (System.getenv("DIGITVA_ANDROID_RELEASE_BUILD") == "1" && releaseSigningValues.any { !it || it.trim().isEmpty() }) {
                throw new GradleException("Android release signing credentials are missing")
            }
            if (releaseSigningValues.every { it && !it.trim().isEmpty() }) {
                storeFile file(releaseStoreFile)
                storePassword releaseKeystorePassword
                keyAlias releaseKeyAlias
                keyPassword releaseKeyPassword
            }
        }`;

function patchAndroidReleaseSigning(contents, env = process.env) {
  validateReleaseSigningEnv(env);
  if (typeof contents !== "string") throw new Error("Android Gradle contents must be a string");

  const signingConfigs = findOnlyBlock(contents, "signingConfigs");
  const debugSigning = findBlock(signingConfigs.body, "debug");
  if (!debugSigning) throw new Error("Unsupported Android Gradle template: missing debug signing config");
  const existingReleaseSigning = findBlock(signingConfigs.body, "release");
  let updated = contents;
  if (!existingReleaseSigning) {
    const insertion = signingConfigs.open + 1 + signingConfigs.body.length;
    updated = `${contents.slice(0, insertion)}${RELEASE_SIGNING_BLOCK}\n    ${contents.slice(insertion)}`;
  } else if (!existingReleaseSigning.body.includes("DigitVA release signing")) {
    throw new Error("Unsupported Android Gradle template: unexpected release signing config");
  }

  const buildTypes = findOnlyBlock(updated, "buildTypes");
  const releaseBuild = findBlock(buildTypes.body, "release");
  if (!releaseBuild) throw new Error("Unsupported Android Gradle template: missing release build type");
  const releaseBody = releaseBuild.body;
  if (/signingConfig\s+signingConfigs\.debug\b/.test(releaseBody)) {
    const absoluteStart = buildTypes.open + 1 + releaseBuild.start;
    const bodyStart = absoluteStart + releaseBody.indexOf("signingConfig");
    updated = `${updated.slice(0, bodyStart)}${updated.slice(bodyStart).replace(
      "signingConfig signingConfigs.debug",
      "signingConfig signingConfigs.release"
    )}`;
  } else if (!/signingConfig\s+signingConfigs\.release\b/.test(releaseBody)) {
    throw new Error("Unsupported Android Gradle template: release build type has no signing config");
  }
  return updated;
}

module.exports = function withAndroidReleaseSigning(config) {
  return withAppBuildGradle(config, (config) => {
    if (config.modResults.language !== "groovy") {
      throw new Error("withAndroidReleaseSigning requires an app/build.gradle Groovy template");
    }
    config.modResults.contents = patchAndroidReleaseSigning(config.modResults.contents);
    return config;
  });
};

module.exports.patchAndroidReleaseSigning = patchAndroidReleaseSigning;
module.exports.validateReleaseSigningEnv = validateReleaseSigningEnv;
module.exports.releaseBuildRequested = releaseBuildRequested;
