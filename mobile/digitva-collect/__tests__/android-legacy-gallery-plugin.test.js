const { addLegacyGallery } = require("../plugins/with-android-legacy-gallery");
const appJson = require("../app.json");

const NAME = "android.permission.READ_EXTERNAL_STORAGE";
const WRITE = "android.permission.WRITE_EXTERNAL_STORAGE";

it("declares the storage read permission for API 32 and below only", () => {
  const { manifest } = addLegacyGallery({ manifest: { "uses-permission": [] } });
  expect(manifest["uses-permission"]).toEqual([
    { $: { "android:name": NAME, "android:maxSdkVersion": "32", "tools:replace": "android:maxSdkVersion" } },
    { $: { "android:name": WRITE, "android:maxSdkVersion": "28", "tools:replace": "android:maxSdkVersion" } },
  ]);
});

it("replaces an unbounded or removing declaration instead of adding a second", () => {
  const { manifest } = addLegacyGallery({ manifest: { "uses-permission": [{ $: { "android:name": NAME, "tools:node": "remove" } }] } });
  expect(manifest["uses-permission"]).toHaveLength(2);
  expect(manifest["uses-permission"][0].$["android:maxSdkVersion"]).toBe("32");
});

it("is wired in app.json, with the capped storage permissions not blocked and media-wide reads absent", () => {
  expect(appJson.expo.plugins).toContain("./plugins/with-android-legacy-gallery");
  expect(appJson.expo.android.blockedPermissions).not.toContain(WRITE);
  expect(appJson.expo.android.blockedPermissions).not.toContain(NAME);
  expect(appJson.expo.android.permissions).not.toContain("READ_MEDIA_IMAGES");
});
