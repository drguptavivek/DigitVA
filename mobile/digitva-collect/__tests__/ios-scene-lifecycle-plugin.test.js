const fs = require("node:fs");
const path = require("node:path");
const { patchAppDelegate, sceneManifest } = require("../plugins/with-ios-scene-lifecycle");

const TEMPLATE = fs.readFileSync(path.join(__dirname, "fixtures", "expo57-AppDelegate.swift"), "utf8");

describe("iOS scene life cycle plugin", () => {
  it("hands window creation to the scene delegate", () => {
    expect(TEMPLATE).toContain("window = UIWindow(frame: UIScreen.main.bounds)");
    const out = patchAppDelegate(TEMPLATE);
    expect(out).toContain("class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {");
    expect(out).not.toContain("UIWindow(frame:");
    expect(out).not.toContain("startReactNative");
    expect(out).toContain("reactNativeFactory = factory");
  });

  it("is idempotent", () => {
    const once = patchAppDelegate(TEMPLATE);
    expect(patchAppDelegate(once)).toBe(once);
  });

  it("refuses an AppDelegate it does not recognise", () => {
    expect(() => patchAppDelegate("class AppDelegate: UIResponder {}")).toThrow(/ExpoAppDelegate/);
  });

  it("registers Expo's scene delegate", () => {
    const manifest = sceneManifest();
    expect(manifest.UISceneConfigurations.UIWindowSceneSessionRoleApplication[0].UISceneDelegateClassName).toBe(
      "EXExpoAppSceneDelegate"
    );
  });
});
