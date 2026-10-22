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
});
