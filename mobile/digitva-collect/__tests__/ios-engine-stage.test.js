const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { findXcframework, stageSmartvaIos } = require("../modules/digitva-smartva/scripts/stage-engine");
const { findIosEngine, stageIcd11Ios } = require("../modules/digitva-icd11/scripts/stage-engine");

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

describe("SmartVA iOS xcframework staging", () => {
  it("copies the private xcframework into the module's ios folder and replaces a changed copy", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-ios-stage-"));
    try {
      const moduleDir = path.join(root, "mobile", "digitva-collect", "modules", "digitva-smartva");
      const source = path.join(root, "private", "generated", "smartva-ios", "SmartvaRust.xcframework");
      write(path.join(source, "Info.plist"), "<plist/>");
      write(path.join(source, "ios-arm64", "SmartvaRust.framework", "SmartvaRust"), "abc");
      fs.mkdirSync(moduleDir, { recursive: true });

      expect(findXcframework(moduleDir)).toBe(source);
      const first = stageSmartvaIos({ moduleDir });
      expect(first.destination).toBe(path.join(moduleDir, "ios", "SmartvaRust.xcframework"));
      expect(fs.readFileSync(path.join(first.destination, "ios-arm64", "SmartvaRust.framework", "SmartvaRust"), "utf8")).toBe("abc");

      // Same size, new bytes, and a file the new build no longer has: the staged copy is replaced as a whole.
      write(path.join(first.destination, "stale.txt"), "old");
      write(path.join(source, "ios-arm64", "SmartvaRust.framework", "SmartvaRust"), "xyz");
      const second = stageSmartvaIos({ moduleDir });
      expect(second.sha256).not.toBe(first.sha256);
      expect(fs.readFileSync(path.join(second.destination, "ios-arm64", "SmartvaRust.framework", "SmartvaRust"), "utf8")).toBe("xyz");
      expect(fs.existsSync(path.join(second.destination, "stale.txt"))).toBe(false);
      expect(stageSmartvaIos({ moduleDir }).sha256).toBe(second.sha256);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails with a plain message when the xcframework is missing, even if the archives were built", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-ios-stage-empty-"));
    try {
      // The Linux part of build-smartva-ios.sh leaves archives and frameworks but no xcframework.
      write(path.join(root, "private", "generated", "smartva-ios", "aarch64-apple-ios", "libsmartva_rust.a"), "a");
      const moduleDir = path.join(root, "modules", "digitva-smartva");
      fs.mkdirSync(moduleDir, { recursive: true });
      expect(() => stageSmartvaIos({ moduleDir })).toThrow("private/generated/smartva-ios/SmartvaRust.xcframework");
      expect(fs.existsSync(path.join(moduleDir, "ios", "SmartvaRust.xcframework"))).toBe(false);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("ICD-11 iOS engine staging", () => {
  function spikeAndEngine(root) {
    const spike = path.join(root, "private", "icd11-offline-spike");
    write(path.join(spike, "bridge-aot", "pub-bionic", "digitva_icd11.so"), "android-only");
    write(path.join(spike, "bundle_min", "appsettings.json"), "{}");
    write(path.join(spike, "bundle_min", "Data", "languageResources.txt"), "lang");
    write(path.join(spike, "data", "icd11_2026-01-17_release-icf-mms_en.pbf.gz"), "release");
    write(path.join(spike, "data", "ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip"), "index");
    write(path.join(spike, "data", "DORIS_v2.1_1.2.0", "Rules.json"), "[]");
    write(path.join(spike, "data", "DORIS_v2.1_1.2.0", "log.txt"), "engine log, never shipped");
    const engine = path.join(root, "private", "generated", "icd11-ios", "DigitvaIcd11Engine.xcframework");
    write(path.join(engine, "Info.plist"), "<plist/>");
    write(path.join(engine, "ios-arm64", "DigitvaIcd11Engine.framework", "DigitvaIcd11Engine"), "engine");
    return { spike, engine };
  }

  it("stages the xcframework and the Android data files under their original names, with the WHO manifest", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "icd11-ios-stage-"));
    try {
      const { engine } = spikeAndEngine(root);
      const moduleDir = path.join(root, "mobile", "digitva-collect", "modules", "digitva-icd11");
      fs.mkdirSync(moduleDir, { recursive: true });
      expect(findIosEngine({}, moduleDir)).toBe(engine);

      const data = path.join(moduleDir, "ios", "Icd11Data");
      write(path.join(data, "data", "old-release.pbf.gz"), "left from an older staging");
      const staged = stageIcd11Ios({ moduleDir, env: {} });

      expect(fs.readFileSync(path.join(moduleDir, "ios", "DigitvaIcd11Engine.xcframework", "ios-arm64", "DigitvaIcd11Engine.framework", "DigitvaIcd11Engine"), "utf8")).toBe("engine");
      expect(fs.readFileSync(path.join(data, "bundle", "appsettings.json"), "utf8")).toBe("{}");
      expect(fs.readFileSync(path.join(data, "data", "icd11_2026-01-17_release-icf-mms_en.pbf.gz"), "utf8")).toBe("release");
      expect(fs.existsSync(path.join(data, "data", "DORIS_v2.1_1.2.0", "Rules.json"))).toBe(true);
      expect(fs.existsSync(path.join(data, "data", "DORIS_v2.1_1.2.0", "log.txt"))).toBe(false);
      expect(fs.existsSync(path.join(data, "data", "old-release.pbf.gz"))).toBe(false);
      // The Android library and the ".bin" asset names are Android's only.
      expect(fs.existsSync(path.join(data, "bridge-aot"))).toBe(false);
      expect(fs.existsSync(path.join(data, "bundle", "appsettings.json.bin"))).toBe(false);

      const manifest = JSON.parse(fs.readFileSync(path.join(data, "who-files.json"), "utf8"));
      expect(manifest).toEqual(staged.who);
      expect(manifest.map((file) => file.path).sort()).toEqual([
        "bundle/Data/languageResources.txt",
        "data/DORIS_v2.1_1.2.0/Rules.json",
        "data/icd11_2026-01-17_release-icf-mms_en.pbf.gz",
        "data/ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip",
      ]);
      expect(manifest.find((file) => file.path.endsWith("Rules.json")).size).toBe(2);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails with a plain message when the iOS engine was not built", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "icd11-ios-stage-empty-"));
    try {
      const moduleDir = path.join(root, "modules", "digitva-icd11");
      fs.mkdirSync(moduleDir, { recursive: true });
      expect(findIosEngine({}, moduleDir)).toBeUndefined();
      expect(() => stageIcd11Ios({ moduleDir, env: {} })).toThrow("engine-src/build-ios.sh");
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("still needs the WHO data when only the engine is there", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "icd11-ios-stage-nodata-"));
    try {
      write(path.join(root, "private", "generated", "icd11-ios", "DigitvaIcd11Engine.xcframework", "Info.plist"), "<plist/>");
      const moduleDir = path.join(root, "modules", "digitva-icd11");
      fs.mkdirSync(moduleDir, { recursive: true });
      expect(() => stageIcd11Ios({ moduleDir, env: {} })).toThrow("private/icd11-offline-spike");
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});
