const appJson = require("./app.json");

const DEFAULT_RELEASE_SERVER = "https://digitva.causeofdeathindia.com";
const DEFAULT_ANDROID_VERSION_CODE = 1;
// Base code: release APKs use base * 10 + ABI digit (plugins/with-android-abi-splits.js),
// which must stay within Android's 2,100,000,000 limit.
const MAX_ANDROID_VERSION_CODE = 209_999_999;

function normalizeHttpsOrigin(raw) {
  try {
    const url = new URL(String(raw || "").trim());
    if (
      url.protocol !== "https:" ||
      !url.hostname ||
      url.username ||
      url.password ||
      (url.pathname !== "" && url.pathname !== "/") ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url.origin.toLowerCase();
  } catch {
    return null;
  }
}

function resolveReleaseServer(env = process.env) {
  const configured = normalizeHttpsOrigin(env.EXPO_PUBLIC_API_BASE_URL);
  if (env.DIGITVA_ANDROID_RELEASE_BUILD === "1" && !configured) {
    throw new Error(
      "DIGITVA_ANDROID_RELEASE_BUILD=1 requires EXPO_PUBLIC_API_BASE_URL to be an exact HTTPS origin"
    );
  }
  return configured || DEFAULT_RELEASE_SERVER;
}

function resolveAndroidVersionCode(env = process.env) {
  if (env.DIGITVA_ANDROID_RELEASE_BUILD !== "1") {
    return DEFAULT_ANDROID_VERSION_CODE;
  }

  const raw = String(env.DIGITVA_ANDROID_VERSION_CODE || "").trim();
  if (!/^\d+$/.test(raw)) {
    throw new Error(
      "DIGITVA_ANDROID_RELEASE_BUILD=1 requires DIGITVA_ANDROID_VERSION_CODE to be a positive integer"
    );
  }

  const versionCode = Number(raw);
  if (
    !Number.isSafeInteger(versionCode) ||
    versionCode < 1 ||
    versionCode > MAX_ANDROID_VERSION_CODE
  ) {
    throw new Error(
      `DIGITVA_ANDROID_VERSION_CODE must be between 1 and ${MAX_ANDROID_VERSION_CODE}`
    );
  }
  return versionCode;
}

// APP_VARIANT=development installs a debug build beside the release app.
// APP_VARIANT=plus is "DigitVA Collect Plus": the experimental adb-only build that carries the offline ICD-11
// engine (docs/policy/field-data-collection.md). It installs beside the release app and is never published.
function resolveVariant(env = process.env) {
  return { isDev: env.APP_VARIANT === "development", isPlus: env.APP_VARIANT === "plus" };
}

module.exports = ({ config = appJson.expo } = {}) => {
  const { isDev, isPlus } = resolveVariant();
  return {
    ...config,
    name: isDev ? "DigitVA Dev" : isPlus ? "DigitVA Collect Plus" : "DigitVA",
    // "-plus" is not major.minor.patch, so Settings' update check reports "unknown" and never offers the plain
    // app's APK over this one.
    version: isPlus ? `${config.version}-plus` : config.version,
    scheme: isDev ? `${config.scheme}dev` : isPlus ? `${config.scheme}plus` : config.scheme,
    // Plus wears the DigitVA icon with a "+" badge, so it is told apart from the plain app on the home screen.
    ...(isPlus ? { icon: "./assets/icon-plus.png" } : {}),
    android: {
      ...config.android,
      ...(isPlus
        ? { adaptiveIcon: { ...config.android.adaptiveIcon, foregroundImage: "./assets/adaptive-icon-plus.png" } }
        : {}),
      package: isDev
        ? `${config.android.package}.dev`
        : isPlus
          ? `${config.android.package}.plus`
          : config.android.package,
      versionCode: resolveAndroidVersionCode(),
    },
    extra: {
      ...config.extra,
      ...(isPlus ? { appVariant: "plus" } : {}),
      digitvaReleaseServer: resolveReleaseServer(),
    },
  };
};

module.exports.resolveVariant = resolveVariant;

module.exports.normalizeHttpsOrigin = normalizeHttpsOrigin;
module.exports.resolveReleaseServer = resolveReleaseServer;
module.exports.resolveAndroidVersionCode = resolveAndroidVersionCode;
