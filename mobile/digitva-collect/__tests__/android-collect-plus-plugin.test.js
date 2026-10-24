const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  patchPlainSettings,
  patchPlusGradle,
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
