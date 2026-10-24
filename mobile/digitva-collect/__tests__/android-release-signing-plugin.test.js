const {
  patchAndroidReleaseSigning,
  releaseSigningRequested,
  validateReleaseSigningEnv,
} = require("../plugins/with-android-release-signing");

const gradle = `
android {
    signingConfigs {
        debug {
            storeFile file('debug.keystore')
            storePassword 'android'
            keyAlias 'androiddebugkey'
            keyPassword 'android'
        }
    }
    buildTypes {
        debug {
            signingConfig signingConfigs.debug
        }
        release {
            signingConfig signingConfigs.debug
        }
    }
}
`;

const releaseEnv = {
  DIGITVA_ANDROID_RELEASE_BUILD: "1",
  ANDROID_RELEASE_STORE_FILE: "/tmp/digitva-release.jks",
  ANDROID_RELEASE_KEYSTORE_PASSWORD: "secret",
  ANDROID_RELEASE_KEY_ALIAS: "digitva",
  ANDROID_RELEASE_KEY_PASSWORD: "secret",
};

describe("withAndroidReleaseSigning", () => {
  it("uses release credentials without changing debug signing", () => {
    const updated = patchAndroidReleaseSigning(gradle, releaseEnv);
    expect(updated).toContain("signingConfig signingConfigs.debug");
    expect(updated).toContain("signingConfig signingConfigs.release");
    expect(updated).toContain("System.getenv(\"ANDROID_RELEASE_STORE_FILE\")");
    expect(updated).not.toContain("storePassword 'secret'");
    expect(patchAndroidReleaseSigning(updated, releaseEnv)).toBe(updated);
  });

  it("allows debug prebuilds without release credentials", () => {
    expect(() => validateReleaseSigningEnv({})).not.toThrow();
    expect(() => patchAndroidReleaseSigning(gradle, {})).not.toThrow();
  });

  it("requires all release credentials only when release intent is set", () => {
    expect(() => validateReleaseSigningEnv({ DIGITVA_ANDROID_RELEASE_BUILD: "1" })).toThrow(
      "requires ANDROID_RELEASE_STORE_FILE"
    );
    expect(() => validateReleaseSigningEnv({ ...releaseEnv, ANDROID_RELEASE_STORE_FILE: "key.jks" })).toThrow(
      "must be an absolute path"
    );
  });

  it("signs plus with the release key only in the release build, debug otherwise", () => {
    expect(releaseSigningRequested({})).toBe(true);
    expect(releaseSigningRequested({ APP_VARIANT: "plus" })).toBe(false);
    expect(releaseSigningRequested({ APP_VARIANT: "plus", DIGITVA_ANDROID_RELEASE_BUILD: "1" })).toBe(true);
  });

  it("fails an unknown Gradle template instead of guessing", () => {
    expect(() => patchAndroidReleaseSigning("android { }", releaseEnv)).toThrow(
      "expected exactly one signingConfigs block"
    );
  });
});
