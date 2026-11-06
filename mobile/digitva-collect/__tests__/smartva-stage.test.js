const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { findLibrary, stageSmartva, stageSmartvaIos } = require("../modules/digitva-smartva/scripts/stage-engine");

describe("SmartVA private library staging", () => {
  it("copies the private library into the Plus module and updates same-size changes", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-stage-"));
    const moduleDir = path.join(root, "mobile", "digitva-collect", "modules", "digitva-smartva");
    const source = path.join(root, "private", "generated", "smartva-android", "arm64-v8a", "libsmartva_rust.so");
    fs.mkdirSync(path.dirname(source), { recursive: true });
    fs.mkdirSync(moduleDir, { recursive: true });
    fs.writeFileSync(source, "abc");

    const first = stageSmartva({ moduleDir });
    expect(first.bytes).toBe(3);
    expect(fs.readFileSync(first.destination, "utf8")).toBe("abc");
    fs.writeFileSync(source, "xyz");
    stageSmartva({ moduleDir });
    expect(fs.readFileSync(first.destination, "utf8")).toBe("xyz");
    expect(findLibrary(moduleDir)).toBe(source);

    fs.rmSync(root, { recursive: true, force: true });
  });

  it("copies the private iOS xcframework into the Plus module, replacing an older one", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-stage-ios-"));
    const moduleDir = path.join(root, "mobile", "digitva-collect", "modules", "digitva-smartva");
    const source = path.join(root, "private", "generated", "smartva-ios", "SmartvaRust.xcframework");
    fs.mkdirSync(path.join(source, "ios-arm64"), { recursive: true });
    fs.mkdirSync(moduleDir, { recursive: true });
    fs.writeFileSync(path.join(source, "Info.plist"), "plist");
    fs.writeFileSync(path.join(source, "ios-arm64", "libsmartva_rust.a"), "new");
    const stale = path.join(moduleDir, "ios", "Engine", "SmartvaRust.xcframework", "old-slice");
    fs.mkdirSync(path.dirname(stale), { recursive: true });
    fs.writeFileSync(stale, "old");

    const staged = stageSmartvaIos({ moduleDir });
    expect(staged.source).toBe(source);
    expect(fs.readFileSync(path.join(staged.destination, "ios-arm64", "libsmartva_rust.a"), "utf8")).toBe("new");
    expect(fs.existsSync(stale)).toBe(false);

    fs.rmSync(root, { recursive: true, force: true });
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-stage-ios-empty-"));
    expect(() => stageSmartvaIos({ moduleDir: empty })).toThrow("scripts/build-smartva-ios.sh");
    fs.rmSync(empty, { recursive: true, force: true });
  });

  it("fails with a plain message when the private library is missing", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-stage-empty-"));
    expect(() => stageSmartva({ moduleDir: root })).toThrow("private/generated/smartva-android/arm64-v8a/libsmartva_rust.so");
    fs.rmSync(root, { recursive: true, force: true });
  });
});
