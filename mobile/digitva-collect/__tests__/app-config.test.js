const appConfig = require("../app.config");

describe("Expo release configuration", () => {
  const originalApi = process.env.EXPO_PUBLIC_API_BASE_URL;
  const originalIntent = process.env.DIGITVA_ANDROID_RELEASE_BUILD;
  const originalVersionCode = process.env.DIGITVA_ANDROID_VERSION_CODE;

  afterEach(() => {
    if (originalApi === undefined) delete process.env.EXPO_PUBLIC_API_BASE_URL;
    else process.env.EXPO_PUBLIC_API_BASE_URL = originalApi;
    if (originalIntent === undefined) delete process.env.DIGITVA_ANDROID_RELEASE_BUILD;
    else process.env.DIGITVA_ANDROID_RELEASE_BUILD = originalIntent;
    if (originalVersionCode === undefined) delete process.env.DIGITVA_ANDROID_VERSION_CODE;
    else process.env.DIGITVA_ANDROID_VERSION_CODE = originalVersionCode;
  });

  it("uses the configured exact origin for a release build", () => {
    process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
    process.env.EXPO_PUBLIC_API_BASE_URL = "https://digitvav3.causeofdeathindia.com/";
    process.env.DIGITVA_ANDROID_VERSION_CODE = "42";
    const resolved = appConfig({ config: require("../app.json").expo });
    expect(resolved.name).toBe("DigitVA");
    expect(resolved.extra.digitvaReleaseServer).toBe(
      "https://digitvav3.causeofdeathindia.com"
    );
    expect(resolved.android.versionCode).toBe(42);
  });

  it("fails a release build when the origin is missing or unsafe", () => {
    process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
    process.env.DIGITVA_ANDROID_VERSION_CODE = "2";
    for (const value of [undefined, "http://digitvav3.causeofdeathindia.com/api"]) {
      if (value === undefined) delete process.env.EXPO_PUBLIC_API_BASE_URL;
      else process.env.EXPO_PUBLIC_API_BASE_URL = value;
      expect(() => appConfig({ config: require("../app.json").expo })).toThrow(
        "requires EXPO_PUBLIC_API_BASE_URL"
      );
    }
  });

  it("keeps the development fallback when release intent is absent", () => {
    delete process.env.DIGITVA_ANDROID_RELEASE_BUILD;
    delete process.env.EXPO_PUBLIC_API_BASE_URL;
    delete process.env.DIGITVA_ANDROID_VERSION_CODE;
    expect(appConfig({ config: require("../app.json").expo }).extra.digitvaReleaseServer).toBe(
      "https://digitva.causeofdeathindia.com"
    );
    expect(appConfig({ config: require("../app.json").expo }).android.versionCode).toBe(1);
  });

  it("requires a valid release version code", () => {
    process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
    process.env.EXPO_PUBLIC_API_BASE_URL = "https://digitvav3.causeofdeathindia.com";
    for (const value of [undefined, "", "0", "-1", "1.5", "1e3", "not-a-number"]) {
      if (value === undefined) delete process.env.DIGITVA_ANDROID_VERSION_CODE;
      else process.env.DIGITVA_ANDROID_VERSION_CODE = value;
      expect(() => appConfig({ config: require("../app.json").expo })).toThrow(
        "DIGITVA_ANDROID_VERSION_CODE"
      );
    }
  });

  it("rejects version codes above the Android limit", () => {
    process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
    process.env.EXPO_PUBLIC_API_BASE_URL = "https://digitvav3.causeofdeathindia.com";
    process.env.DIGITVA_ANDROID_VERSION_CODE = "2100000001";
    expect(() => appConfig({ config: require("../app.json").expo })).toThrow(
      "between 1 and 2100000000"
    );
  });
});
