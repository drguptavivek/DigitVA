const { withAndroidManifest } = require("@expo/config-plugins");

const NAME = "android.permission.READ_EXTERNAL_STORAGE";

/**
 * Android 12 and older (API 32) need READ_EXTERNAL_STORAGE to choose a photograph from the gallery; Android 13+
 * uses the system photo picker and needs none. Declared with maxSdkVersion 32 so newer phones never hold it.
 * Images only: no media-wide permission (docs/policy/phone-attachments.md).
 */
function addLegacyGallery(manifest) {
  const permissions = (manifest.manifest["uses-permission"] ??= []);
  const entry = { $: { "android:name": NAME, "android:maxSdkVersion": "32" } };
  const index = permissions.findIndex((permission) => permission.$?.["android:name"] === NAME);
  if (index >= 0) permissions[index] = entry;
  else permissions.push(entry);
  return manifest;
}

module.exports = (config) => withAndroidManifest(config, (c) => {
  c.modResults = addLegacyGallery(c.modResults);
  return c;
});
module.exports.addLegacyGallery = addLegacyGallery;
