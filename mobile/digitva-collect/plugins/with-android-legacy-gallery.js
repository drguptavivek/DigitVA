const { withAndroidManifest } = require("@expo/config-plugins");

const NAME = "android.permission.READ_EXTERNAL_STORAGE";
const WRITE = "android.permission.WRITE_EXTERNAL_STORAGE";

/**
 * Android 12 and older (API 32) need READ_EXTERNAL_STORAGE to choose a photograph from the gallery; Android 13+
 * uses the system photo picker and needs none. Declared with maxSdkVersion 32 so newer phones never hold it.
 * Android 9 and older (API 28): expo-image-picker refuses the camera and the gallery without
 * WRITE_EXTERNAL_STORAGE, so it is declared with maxSdkVersion 28; Android 10+ never holds it.
 * Images only: no media-wide permission (docs/policy/phone-attachments.md).
 */
function declare(permissions, name, maxSdk) {
  // tools:replace: a library (expo-file-system) declares its own maxSdkVersion; ours must win in the merge.
  const entry = { $: { "android:name": name, "android:maxSdkVersion": maxSdk, "tools:replace": "android:maxSdkVersion" } };
  const index = permissions.findIndex((permission) => permission.$?.["android:name"] === name);
  if (index >= 0) permissions[index] = entry;
  else permissions.push(entry);
}

function addLegacyGallery(manifest) {
  manifest.manifest.$ = { ...manifest.manifest.$, "xmlns:tools": "http://schemas.android.com/tools" };
  const permissions = (manifest.manifest["uses-permission"] ??= []);
  declare(permissions, NAME, "32");
  declare(permissions, WRITE, "28");
  return manifest;
}

module.exports = (config) => withAndroidManifest(config, (c) => {
  c.modResults = addLegacyGallery(c.modResults);
  return c;
});
module.exports.addLegacyGallery = addLegacyGallery;
