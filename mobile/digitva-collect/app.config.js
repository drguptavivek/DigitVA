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
const isDev = process.env.APP_VARIANT === "development";

module.exports = ({ config = appJson.expo } = {}) => ({
  ...config,
  name: isDev ? "DigitVA Dev" : "DigitVA",
  scheme: isDev ? `${config.scheme}dev` : config.scheme,
  android: {
    ...config.android,
    package: isDev ? `${config.android.package}.dev` : config.android.package,
    versionCode: resolveAndroidVersionCode(),
  },
  extra: {
    ...config.extra,
    digitvaReleaseServer: resolveReleaseServer(),
  },
});

module.exports.normalizeHttpsOrigin = normalizeHttpsOrigin;
module.exports.resolveReleaseServer = resolveReleaseServer;
module.exports.resolveAndroidVersionCode = resolveAndroidVersionCode;
