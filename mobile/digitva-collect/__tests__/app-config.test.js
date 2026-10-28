const appConfig = require("../app.config");

describe("Expo release configuration", () => {
  const originalApi = process.env.EXPO_PUBLIC_API_BASE_URL;
  const originalIntent = process.env.DIGITVA_ANDROID_RELEASE_BUILD;
  const originalVersionCode = process.env.DIGITVA_ANDROID_VERSION_CODE;
  const originalDistribution = process.env.DIGITVA_DISTRIBUTION;

  // Every case starts as the sideloaded build unless it sets the Play flag itself.
  beforeEach(() => {
    delete process.env.DIGITVA_DISTRIBUTION;
  });

  afterEach(() => {
    if (originalDistribution === undefined) delete process.env.DIGITVA_DISTRIBUTION;
    else process.env.DIGITVA_DISTRIBUTION = originalDistribution;
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
      "https://digitvav3.causeofdeathindia.com"
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
    process.env.DIGITVA_ANDROID_VERSION_CODE = "210000000";
    expect(() => appConfig({ config: require("../app.json").expo })).toThrow(
      "between 1 and 209999999"
    );
  });

  describe("Google Play distribution", () => {
    const resolve = () => appConfig({ config: require("../app.json").expo });
    const releaseEnv = () => {
      process.env.DIGITVA_ANDROID_RELEASE_BUILD = "1";
      process.env.EXPO_PUBLIC_API_BASE_URL = "https://digitvav3.causeofdeathindia.com";
      process.env.DIGITVA_ANDROID_VERSION_CODE = "311";
    };

    it("marks the Play build and puts its versionCode above both per-ABI APKs", () => {
      releaseEnv();
      process.env.DIGITVA_DISTRIBUTION = "play";
      const resolved = resolve();
      expect(resolved.extra.digitvaDistribution).toBe("play");
      expect(resolved.android.versionCode).toBe(3113);
      expect(resolved.android.package).toBe("com.causeofdeathindia.digitvacollect");
    });

    it("keeps the highest base within Android's versionCode limit", () => {
      releaseEnv();
      process.env.DIGITVA_DISTRIBUTION = "play";
      process.env.DIGITVA_ANDROID_VERSION_CODE = "209999999";
      expect(resolve().android.versionCode).toBe(2_099_999_993);
    });

    it("leaves the sideloaded build unchanged without the flag", () => {
      releaseEnv();
      const resolved = resolve();
      expect(resolved.extra.digitvaDistribution).toBe("sideload");
      expect(resolved.android.versionCode).toBe(311);
    });

    it("refuses an unknown distribution value", () => {
      releaseEnv();
      process.env.DIGITVA_DISTRIBUTION = "Play";
      expect(resolve).toThrow("DIGITVA_DISTRIBUTION");
    });
  });

  describe("Collect Plus variant", () => {
    // CI release jobs export these for the whole job; the variant tests must not depend on them.
    const keys = ["APP_VARIANT", "DIGITVA_ANDROID_RELEASE_BUILD", "DIGITVA_ANDROID_VERSION_CODE"];
    const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
    beforeEach(() => {
      delete process.env.DIGITVA_ANDROID_RELEASE_BUILD;
      delete process.env.DIGITVA_ANDROID_VERSION_CODE;
    });
    afterEach(() => {
      for (const key of keys) {
        if (saved[key] === undefined) delete process.env[key];
        else process.env[key] = saved[key];
      }
    });
    const resolve = () => appConfig({ config: require("../app.json").expo });

    it("names, packages and tags the plus build, beside the plain app", () => {
      process.env.APP_VARIANT = "plus";
      const resolved = resolve();
      expect(resolved.name).toBe("DigitVA Collect Plus");
      expect(resolved.android.package).toBe("com.causeofdeathindia.digitvacollect.plus");
      expect(resolved.version).toBe(`${require("../app.json").expo.version}-plus`);
      expect(resolved.scheme).toBe("digitvacollectplus");
      expect(resolved.extra.appVariant).toBe("plus");
      expect(resolved.icon).toBe("./assets/icon-plus.png");
      expect(resolved.android.adaptiveIcon).toEqual({ foregroundImage: "./assets/adaptive-icon-plus.png", backgroundColor: "#FFFFFF" });
      expect(require("node:fs").existsSync(require("node:path").join(__dirname, "../assets/icon-plus.png"))).toBe(true);
    });

    it("leaves the plain build exactly as before", () => {
      delete process.env.APP_VARIANT;
      const resolved = resolve();
      expect(resolved.name).toBe("DigitVA");
      expect(resolved.android.package).toBe("com.causeofdeathindia.digitvacollect");
      expect(resolved.version).toBe(require("../app.json").expo.version);
      expect(resolved.scheme).toBe("digitvacollect");
      expect(resolved.extra).not.toHaveProperty("appVariant");
      expect(resolved.icon).toBe("./assets/icon.png");
      expect(resolved.android.adaptiveIcon.foregroundImage).toBe("./assets/adaptive-icon.png");
    });

    it("keeps the development variant separate from plus", () => {
      process.env.APP_VARIANT = "development";
      const resolved = resolve();
      expect(resolved.name).toBe("DigitVA Dev");
      expect(resolved.android.package).toBe("com.causeofdeathindia.digitvacollect.dev");
      expect(resolved.extra).not.toHaveProperty("appVariant");
    });
  });
});
