const fs = require("node:fs");
const path = require("node:path");

// Source checks for the iOS sides of the local native modules. The Swift is compiled only on a Mac
// (.github/workflows/ios-build.yml); these keep its contract with the JS and the Android side from drifting.
const modules = path.join(__dirname, "..", "modules");
const read = (...parts) => fs.readFileSync(path.join(modules, ...parts), "utf8");
const config = (name) => JSON.parse(read(name, "expo-module.config.json"));

describe("iOS module registration", () => {
  it.each([
    ["digitva-device-info", "DigitvaDeviceInfoModule", "DigitvaDeviceInfo"],
    ["digitva-smartva", "DigitvaSmartvaModule", "DigitvaSmartva"],
    ["digitva-icd11", "DigitvaIcd11Module", "DigitvaIcd11"],
  ])("%s declares its Swift module under the same JS name as Android", (name, swiftClass, jsName) => {
    const { platforms, apple } = config(name);
    expect(platforms).toEqual(["android", "apple"]);
    expect(apple.modules).toEqual([swiftClass]);
    const swift = read(name, "ios", `${swiftClass}.swift`);
    expect(swift).toContain(`public final class ${swiftClass}: Module`);
    expect(swift).toContain(`Name("${jsName}")`);
    expect(fs.existsSync(path.join(modules, name, "ios", `${jsName}.podspec`))).toBe(true);
  });
});

describe("DigitvaDeviceInfo on iOS", () => {
  it("returns only values src/performanceTelemetry.ts accepts", () => {
    const swift = read("digitva-device-info", "ios", "DigitvaDeviceInfoModule.swift");
    const strings = [...swift.matchAll(/return "([a-z0-9_]+)"/g)].map((match) => match[1]);
    const allowed = new Set(["phone", "tablet", "emulator", "other", "unknown", "lt2", "2_3", "4_5", "6_7", "8_11", "12plus", "1_2", "3_4", "5_8", "9plus"]);
    expect(strings.length).toBeGreaterThan(10);
    for (const value of strings) expect(allowed).toContain(value);
    expect(swift).toContain('"manufacturer": "apple"');
  });
});

describe("DigitvaSmartva on iOS", () => {
  const swift = read("digitva-smartva", "ios", "DigitvaSmartvaModule.swift");
  const podspec = read("digitva-smartva", "ios", "DigitvaSmartva.podspec");

  it("links the engine only when the staged xcframework is vendored", () => {
    expect(podspec).toContain("File.directory?(File.join(__dir__, 'SmartvaRust.xcframework'))");
    expect(podspec).toContain("DIGITVA_SMARTVA_LINKED");
    expect(swift).toMatch(/#if DIGITVA_SMARTVA_LINKED\nimport SmartvaRust\n#endif/);
  });

  it("keeps Android's limits and frees every C-ABI result and error pointer, with no eager warm-up", () => {
    expect(swift).toContain("maxRequestBytes = 1024 * 1024");
    expect(swift).toContain("maxReplyBytes = 2 * 1024 * 1024");
    expect(swift).toContain("if let error { smartva_free_string(error) }");
    expect(swift).toContain("defer { smartva_free_string(result) }");
    expect(swift).not.toContain("smartva_warm_cache");
    for (const code of ["too_large", "bad_request", "engine_error", "native_error", "unavailable"]) expect(swift).toContain(`"${code}"`);
  });
});

describe("DigitvaIcd11 on iOS", () => {
  const swift = read("digitva-icd11", "ios", "DigitvaIcd11Module.swift");
  const data = read("digitva-icd11", "ios", "EngineData.swift");
  const kotlinData = read("digitva-icd11", "android", "src", "main", "java", "expo", "modules", "digitvaicd11", "EngineData.kt");

  it("exposes the NativeEngine API with Android's op check and error code", () => {
    for (const name of ["isAvailable", "init", "updateWhoFiles", "call"]) expect(swift).toContain(`AsyncFunction("${name}")`);
    expect(swift).toContain('Events("icd11Progress")');
    expect(swift).toContain('promise.reject("ERR_ICD11_OP", "bad engine op")');
    expect(swift).toContain('"bundled_only"');
    expect(swift).toContain("stackSize: 32 << 20");
  });

  it("frees engine strings and never returns the engine's error text", () => {
    expect(swift).toContain("digitva_icd11_free(error)");
    expect(swift).toContain("defer { digitva_icd11_free(out) }");
    expect(swift).not.toMatch(/String\(cString: error\)/);
  });

  it("uses the same data version as Android and protects the copied data", () => {
    const kotlinVersion = kotlinData.match(/DATA_VERSION = "([^"]+)"/)[1];
    expect(data).toContain(`dataVersion = "${kotlinVersion}"`);
    expect(data).toContain("isExcludedFromBackup = true");
    expect(data).toContain("completeUntilFirstUserAuthentication");
  });
});
