const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { findLibrary, stageSmartva } = require("../modules/digitva-smartva/scripts/stage-engine");

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

  it("fails with a plain message when the private library is missing", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "smartva-stage-empty-"));
    expect(() => stageSmartva({ moduleDir: root })).toThrow("private/generated/smartva-android/arm64-v8a/libsmartva_rust.so");
    fs.rmSync(root, { recursive: true, force: true });
  });
});
