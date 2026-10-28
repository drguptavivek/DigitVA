const { patchAndroidAbiSplits, RELEASE_ABIS } = require("../plugins/with-android-abi-splits");

describe("withAndroidAbiSplits", () => {
  const gradle = "android {\n    defaultConfig { versionCode 1 }\n}\n";

  it("splits release APKs per ARM ABI with distinct version codes", () => {
    const updated = patchAndroidAbiSplits(gradle);
    expect(RELEASE_ABIS).toEqual(["armeabi-v7a", "arm64-v8a"]);
    expect(updated).toContain('include "armeabi-v7a", "arm64-v8a"');
    expect(updated).toContain("universalApk false");
    expect(updated).toContain('["armeabi-v7a": 1, "arm64-v8a": 2][abi]');
    expect(updated).toContain("output.versionCode.get() * 10 + abiDigit");
    expect(updated.startsWith(gradle.trimEnd())).toBe(true);
  });

  it("is idempotent", () => {
    const once = patchAndroidAbiSplits(gradle);
    expect(patchAndroidAbiSplits(once)).toBe(once);
  });

  it("rejects non-string Gradle contents", () => {
    expect(() => patchAndroidAbiSplits(undefined)).toThrow("must be a string");
  });

  describe("release builds", () => {
    const withAndroidAbiSplits = require("../plugins/with-android-abi-splits");
    const keys = ["APP_VARIANT", "DIGITVA_ANDROID_RELEASE_BUILD", "DIGITVA_DISTRIBUTION"];
    const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
    beforeEach(() => {
      delete process.env.APP_VARIANT;
      process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
    });
    afterEach(() => {
      for (const key of keys) {
        if (saved[key] === undefined) delete process.env[key];
        else process.env[key] = saved[key];
      }
    });

    it("splits the sideloaded release build", () => {
      delete process.env.DIGITVA_DISTRIBUTION;
      const config = withAndroidAbiSplits({ name: "DigitVA", slug: "digitva" });
      expect(config.mods.android.appBuildGradle).toEqual(expect.any(Function));
      expect(config.mods.android.gradleProperties).toEqual(expect.any(Function));
    });

    it("stands aside for the Google Play bundle", () => {
      process.env.DIGITVA_DISTRIBUTION = "play";
      const input = { name: "DigitVA", slug: "digitva" };
      const config = withAndroidAbiSplits(input);
      expect(config).toBe(input);
      expect(config).not.toHaveProperty("mods");
    });
  });
});
