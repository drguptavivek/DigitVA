const fs = require("node:fs");
const path = require("node:path");
const { excludedModules, patchPlainPodfile, patchPodfile } = require("../plugins/with-ios-collect-plus");

const MODULES = path.join(__dirname, "..", "modules");

describe("withIosCollectPlus", () => {
  it("keeps the engine modules out of the plain build's autolinking, once", () => {
    const podfile = "target 'DigitVA' do\n  use_expo_modules!\n  config = use_native_modules!(config_command)\nend\n";
    const once = patchPlainPodfile(podfile);
    expect(once).toContain('  use_expo_modules!(exclude: ["digitva-icd11", "digitva-smartva"])\n');
    expect(once).not.toMatch(/^\s*use_expo_modules!\s*$/m);
    expect(patchPlainPodfile(once)).toBe(once);
    expect(() => patchPlainPodfile("target 'DigitVA' do\nend\n")).toThrow("use_expo_modules!");
    expect(() => patchPlainPodfile(undefined)).toThrow("must be a string");
  });

  it("excludes both engines for plain, ICD-11 for a SmartVA-only Plus, and none for a full Plus", () => {
    expect(excludedModules({})).toEqual(["digitva-icd11", "digitva-smartva"]);
    expect(excludedModules({ DIGITVA_IOS_SKIP_ICD11: "1" })).toEqual(["digitva-icd11", "digitva-smartva"]);
    expect(excludedModules({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: "1" })).toEqual(["digitva-icd11"]);
    expect(excludedModules({ APP_VARIANT: "plus" })).toEqual([]);
  });

  it("rewrites an exclusion an earlier prebuild left, so a full Plus does not inherit the plain one", () => {
    const podfile = "target 'DigitVA' do\n  use_expo_modules!\nend\n";
    const plain = patchPlainPodfile(podfile);
    expect(patchPodfile(plain, [])).toBe(podfile);
    const smartvaOnly = patchPodfile(plain, ["digitva-icd11"]);
    expect(smartvaOnly).toContain('  use_expo_modules!(exclude: ["digitva-icd11"])\n');
    expect(smartvaOnly).not.toContain("digitva-smartva");
    expect(patchPodfile(podfile, [])).toBe(podfile);
    expect(() => patchPodfile("# DigitVA Collect Plus: engine modules are plus-only\n  use_expo_modules!(foo)\n", []))
      .toThrow("existing Plus exclusion");
  });

  it("links every DigitVA module on iOS with the module class its Swift source defines", () => {
    for (const [dir, name] of [["digitva-icd11", "DigitvaIcd11Module"], ["digitva-smartva", "DigitvaSmartvaModule"], ["digitva-device-info", "DigitvaDeviceInfoModule"]]) {
      const config = JSON.parse(fs.readFileSync(path.join(MODULES, dir, "expo-module.config.json"), "utf8"));
      expect(config.platforms).toEqual(["android", "ios"]);
      expect(config.ios.modules).toEqual([name]);
      expect(fs.readFileSync(path.join(MODULES, dir, "ios", `${name}.swift`), "utf8")).toContain(`public class ${name}: Module`);
    }
  });

  it("keeps the iOS engine on Android's data version", () => {
    const kotlin = fs.readFileSync(path.join(MODULES, "digitva-icd11", "android", "src", "main", "java", "expo", "modules", "digitvaicd11", "EngineData.kt"), "utf8");
    const swift = fs.readFileSync(path.join(MODULES, "digitva-icd11", "ios", "EngineData.swift"), "utf8");
    const version = kotlin.match(/DATA_VERSION = "([^"]+)"/)[1];
    expect(swift).toContain(`static let dataVersion = "${version}"`);
  });

  // Source checks only: the Swift compiles on a Mac (.github/workflows/ios-build.yml); these keep its contract with
  // the JS and the Android side from drifting.
  it("returns only device-info values src/performanceTelemetry.ts accepts", () => {
    const swift = fs.readFileSync(path.join(MODULES, "digitva-device-info", "ios", "DigitvaDeviceInfoModule.swift"), "utf8");
    const values = [...swift.matchAll(/return "([a-z0-9_]+)"/g)].map((match) => match[1]);
    const allowed = new Set(["phone", "tablet", "emulator", "other", "unknown", "lt2", "2_3", "4_5", "6_7", "8_11", "12plus", "1_2", "3_4", "5_8", "9plus"]);
    expect(values.length).toBeGreaterThan(10);
    for (const value of values) expect(allowed).toContain(value);
    expect(swift).toContain('"manufacturer": "apple"');
  });

  it("keeps SmartVA's Android limits and frees every C-ABI string, with no eager warm-up", () => {
    const swift = fs.readFileSync(path.join(MODULES, "digitva-smartva", "ios", "DigitvaSmartvaModule.swift"), "utf8");
    expect(swift).toContain("maxRequestBytes = 1024 * 1024");
    expect(swift).toContain("maxReplyBytes = 2 * 1024 * 1024");
    expect(swift).toContain("if let error { smartva_free_string(error) }");
    expect(swift).toContain("defer { smartva_free_string(result) }");
    expect(swift).not.toContain("smartva_warm_cache");
    expect(swift).toContain('"too_large"');
  });

  it("checks ICD-11 ops, frees engine strings and never returns the engine's error text", () => {
    const module = fs.readFileSync(path.join(MODULES, "digitva-icd11", "ios", "DigitvaIcd11Module.swift"), "utf8");
    const host = fs.readFileSync(path.join(MODULES, "digitva-icd11", "ios", "EngineHost.swift"), "utf8");
    const data = fs.readFileSync(path.join(MODULES, "digitva-icd11", "ios", "EngineData.swift"), "utf8");
    for (const name of ["isAvailable", "init", "updateWhoFiles", "call"]) expect(module).toContain(`AsyncFunction("${name}")`);
    expect(module).toContain('promise.reject("ERR_ICD11_OP", "bad engine op")');
    expect(host).toContain("digitva_icd11_free(error)");
    expect(host).toContain("defer { digitva_icd11_free(out) }");
    expect(host).not.toMatch(/String\(cString: error\)/);
    expect(data).toContain("isExcludedFromBackup = true");
  });
});
