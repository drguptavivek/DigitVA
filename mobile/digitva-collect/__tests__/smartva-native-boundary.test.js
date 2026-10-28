const fs = require("node:fs");
const path = require("node:path");

const moduleDir = path.join(__dirname, "..", "modules", "digitva-smartva");

describe("SmartVA Android source boundary", () => {
  it("is Android-only and runs in a private, isolated service process", () => {
    const config = JSON.parse(fs.readFileSync(path.join(moduleDir, "expo-module.config.json"), "utf8"));
    const manifest = fs.readFileSync(path.join(moduleDir, "android/src/main/AndroidManifest.xml"), "utf8");
    expect(config.platforms).toEqual(["android"]);
    expect(manifest).toContain('android:process=":smartva"');
    expect(manifest).toContain('android:exported="false"');
  });

  it("loads only on explicit native demand and never performs an eager model warm-up", () => {
    const jni = fs.readFileSync(path.join(moduleDir, "android/src/main/java/expo/modules/digitvasmartva/SmartVaJni.kt"), "utf8");
    const service = fs.readFileSync(path.join(moduleDir, "android/src/main/java/expo/modules/digitvasmartva/SmartvaService.kt"), "utf8");
    expect(jni).toContain("fun load()");
    expect(service).toContain("OP_INIT -> initialize()");
    expect(service).not.toContain("smartva_warm_cache");
  });

  it("bounds native results and frees every C-ABI result/error pointer", () => {
    const bridge = fs.readFileSync(path.join(moduleDir, "android/src/main/cpp/SmartVaJni.cpp"), "utf8");
    expect(bridge).toContain("MAX_REQUEST_BYTES = 1024 * 1024");
    expect(bridge).toContain("MAX_REPLY_BYTES = 2 * 1024 * 1024");
    expect(bridge).toContain("if (error) smartva_free_string(error)");
    expect(bridge).toContain("smartva_free_string(result)");
  });
});
