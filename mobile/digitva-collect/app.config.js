const appJson = require("./app.json");
const { playDistributionRequested } = require("./plugins/with-android-release-signing");

const DEFAULT_RELEASE_SERVER = "https://digitvav3.causeofdeathindia.com";
const DEFAULT_ANDROID_VERSION_CODE = 1;
// Base code: release APKs use base * 10 + ABI digit 1 or 2 (plugins/with-android-abi-splits.js) and the
// Google Play AAB uses base * 10 + 3, above both; each must stay within Android's 2,100,000,000 limit.
const PLAY_VERSION_CODE_DIGIT = 3;
const MAX_ANDROID_VERSION_CODE = 209_999_999;
const DEFAULT_IOS_BUILD_NUMBER = "1";

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
  if (env.DIGITVA_IOS_RELEASE_BUILD === "1" && !configured) {
    throw new Error(
      "DIGITVA_IOS_RELEASE_BUILD=1 requires EXPO_PUBLIC_API_BASE_URL to be an exact HTTPS origin"
    );
  }
  return configured || DEFAULT_RELEASE_SERVER;
}

// CFBundleVersion for the App Store / TestFlight upload; each upload of one version needs a higher number.
// Like the Android version code, it is read only for a release build and defaults to "1" otherwise.
function resolveIosBuildNumber(env = process.env) {
  if (env.DIGITVA_IOS_RELEASE_BUILD !== "1") {
    return DEFAULT_IOS_BUILD_NUMBER;
  }
  const raw = String(env.DIGITVA_IOS_BUILD_NUMBER || "").trim();
  const buildNumber = Number(raw);
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(buildNumber) || buildNumber < 1) {
    throw new Error(
      "DIGITVA_IOS_RELEASE_BUILD=1 requires DIGITVA_IOS_BUILD_NUMBER to be a positive integer"
    );
  }
  return String(buildNumber);
}

// The App Store listing id Settings opens on iOS (docs/policy/ios-client.md); optional, digits only.
function resolveIosAppStoreId(env = process.env) {
  const raw = String(env.DIGITVA_IOS_APP_STORE_ID || "").trim();
  if (!raw) return undefined;
  if (!/^\d+$/.test(raw)) {
    throw new Error("DIGITVA_IOS_APP_STORE_ID must be the App Store's numeric app id");
  }
  return raw;
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
  // The splits plugin stands aside for Play, so this is the AAB's final versionCode.
  return playDistributionRequested(env) ? versionCode * 10 + PLAY_VERSION_CODE_DIGIT : versionCode;
}

// APP_VARIANT=development installs a debug build beside the release app.
// APP_VARIANT=plus is "DigitVA Collect Plus": it carries the offline ICD-11 engine and is published as a separate app.
// It installs beside normal Collect (docs/policy/field-data-collection.md).
function resolveVariant(env = process.env) {
  return { isDev: env.APP_VARIANT === "development", isPlus: env.APP_VARIANT === "plus" };
}

module.exports = ({ config = appJson.expo } = {}) => {
  const { isDev, isPlus } = resolveVariant();
  const iosAppStoreId = resolveIosAppStoreId();
  return {
    ...config,
    name: isDev ? "DigitVA Dev" : isPlus ? "DigitVA Collect Plus" : "DigitVA",
    // Store checks reject a suffixed version, so Plus is told apart by name, bundle id and package, not "-plus".
    // The update check asks the server for the variant by package (isPlusVariant), never by this string.
    version: config.version,
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
    // Bundle ids mirror the Android packages so the variants install side by side on iOS too.
    ios: {
      ...config.ios,
      bundleIdentifier: isDev
        ? `${config.ios.bundleIdentifier}.dev`
        : isPlus
          ? `${config.ios.bundleIdentifier}.plus`
          : config.ios.bundleIdentifier,
      buildNumber: resolveIosBuildNumber(),
      supportsTablet: true,
      // Signing team for device builds; unset for CI's unsigned simulator builds.
      ...(process.env.DIGITVA_IOS_TEAM_ID ? { appleTeamId: process.env.DIGITVA_IOS_TEAM_ID } : {}),
      // The in-process ICD-11 engine holds 0.5 to 1.3 GB: Plus asks iOS for the raised memory limit (the App ID
      // must carry the Increased Memory Limit capability, which automatic signing adds).
      ...(isPlus
        ? {
            entitlements: {
              ...(config.ios && config.ios.entitlements),
              "com.apple.developer.kernel.increased-memory-limit": true,
            },
          }
        : {}),
    },
    extra: {
      ...config.extra,
      ...(isPlus ? { appVariant: "plus" } : {}),
      digitvaReleaseServer: resolveReleaseServer(),
      // "play" hides the in-app update check (Play forbids self-update); read by src/appVariant.ts.
      digitvaDistribution: playDistributionRequested() ? "play" : "sideload",
      // iOS is always App Store / TestFlight distribution; this id lets Settings link to the listing.
      ...(iosAppStoreId ? { digitvaIosAppStoreId: iosAppStoreId } : {}),
    },
  };
};

module.exports.resolveVariant = resolveVariant;

module.exports.normalizeHttpsOrigin = normalizeHttpsOrigin;
module.exports.resolveReleaseServer = resolveReleaseServer;
module.exports.resolveAndroidVersionCode = resolveAndroidVersionCode;
module.exports.resolveIosBuildNumber = resolveIosBuildNumber;
module.exports.resolveIosAppStoreId = resolveIosAppStoreId;
