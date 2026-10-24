const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

jest.mock("@expo/config-plugins", () => ({
  ...jest.requireActual("@expo/config-plugins"),
  withGradleProperties: jest.fn((config) => config),
}));

const { withGradleProperties } = require("@expo/config-plugins");
const withAndroidCollectPlus = require("../plugins/with-android-collect-plus");
const {
  addProfileable,
  patchPlainSettings,
  patchPlusGradle,
  patchPlusGradleProperties,
  plusBuildRequested,
} = require("../plugins/with-android-collect-plus");
const { patchAndroidAbiSplits } = require("../plugins/with-android-abi-splits");
const { findSpike, stageEngine } = require("../modules/digitva-icd11/scripts/stage-engine");

describe("withAndroidCollectPlus", () => {
  it("is on only for APP_VARIANT=plus", () => {
    expect(plusBuildRequested({ APP_VARIANT: "plus" })).toBe(true);
    expect(plusBuildRequested({ APP_VARIANT: "development" })).toBe(false);
    expect(plusBuildRequested({})).toBe(false);
  });

  it("keeps the engine module out of the plain build's autolinking, once", () => {
    const settings = "rootProject.name = 'DigitVA'\nexpoAutolinking.useExpoModules()\ninclude ':app'\n";
    const once = patchPlainSettings(settings);
    expect(once).toContain('expoAutolinking.exclude = ["digitva-icd11"]\nexpoAutolinking.useExpoModules()');
    expect(once.indexOf("exclude")).toBeLessThan(once.indexOf("useExpoModules"));
    expect(patchPlainSettings(once)).toBe(once);
    expect(() => patchPlainSettings("include ':app'")).toThrow("useExpoModules");
  });

  it("extracts native libraries and keeps the engine unstripped, once", () => {
    const gradle = "android {\n}\n";
    const once = patchPlusGradle(gradle);
    expect(once).toContain("useLegacyPackaging = true");
    expect(once).toContain("libdigitva_icd11.so");
    expect(patchPlusGradle(once)).toBe(once);
  });

  it("raises the Gradle JVM heap for plus, replacing an existing entry in place", () => {
    const added = patchPlusGradleProperties([{ type: "property", key: "android.useAndroidX", value: "true" }]);
    expect(added).toEqual([
      { type: "property", key: "android.useAndroidX", value: "true" },
      { type: "property", key: "org.gradle.jvmargs", value: "-Xmx6144m -XX:MaxMetaspaceSize=512m" },
    ]);
    const replaced = patchPlusGradleProperties([
      { type: "property", key: "org.gradle.jvmargs", value: "-Xmx2048m" },
      { type: "property", key: "android.useAndroidX", value: "true" },
    ]);
    expect(replaced.filter((item) => item.key === "org.gradle.jvmargs")).toHaveLength(1);
    expect(replaced[0].value).toBe("-Xmx6144m -XX:MaxMetaspaceSize=512m");
    expect(patchPlusGradleProperties(replaced)).toEqual(replaced);
  });

  it("sets the Gradle JVM heap only in the plus build", () => {
    const saved = process.env.APP_VARIANT;
    try {
      withGradleProperties.mockClear();
      process.env.APP_VARIANT = "development";
      withAndroidCollectPlus({ name: "DigitVA", slug: "digitva" });
      expect(withGradleProperties).not.toHaveBeenCalled();

      process.env.APP_VARIANT = "plus";
      withAndroidCollectPlus({ name: "DigitVA", slug: "digitva" });
      expect(withGradleProperties).toHaveBeenCalledTimes(1);
      const [, action] = withGradleProperties.mock.calls[0];
      const result = action({ modResults: [] });
      expect(result.modResults).toEqual([
        { type: "property", key: "org.gradle.jvmargs", value: "-Xmx6144m -XX:MaxMetaspaceSize=512m" },
      ]);
    } finally {
      process.env.APP_VARIANT = saved;
    }
  });

  it("makes plus profileable for the shell, idempotently", () => {
    const application = { $: { "android:name": ".MainApplication" }, activity: [] };
    const once = addProfileable(application);
    expect(once.profileable).toEqual([{ $: { "android:shell": "true" } }]);
    expect(addProfileable(once).profileable).toHaveLength(1);
    expect(() => addProfileable(undefined)).toThrow("application must be an object");
  });

  it("splits plus into arm64 only, with the same ABI digit as the release arm64 APK", () => {
    const updated = patchAndroidAbiSplits("android {\n}\n", ["arm64-v8a"]);
    expect(updated).toContain('include "arm64-v8a"');
    expect(updated).not.toContain('include "armeabi-v7a"');
    expect(updated).toContain('"arm64-v8a": 2');
  });
});

describe("stage-engine", () => {
  it("fails with a plain message when private/ is missing", () => {
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), "plus-stage-"));
    expect(findSpike({}, empty)).toBeUndefined();
    expect(() => stageEngine({ moduleDir: empty, env: {} })).toThrow("private/icd11-offline-spike");
  });
});
