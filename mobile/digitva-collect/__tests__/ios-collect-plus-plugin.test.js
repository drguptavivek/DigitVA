const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

jest.mock("@expo/config-plugins", () => ({
  ...jest.requireActual("@expo/config-plugins"),
  withPodfile: jest.fn((config) => config),
  withDangerousMod: jest.fn((config) => config),
}));

const { withDangerousMod, withPodfile } = require("@expo/config-plugins");
const withIosCollectPlus = require("../plugins/with-ios-collect-plus");
const { excludedModules, patchPodfileExclude, plusBuildRequested } = require("../plugins/with-ios-collect-plus");

// The target block of Expo SDK 57's template Podfile (node_modules/expo/template.tgz, ios/Podfile).
const PODFILE = `platform :ios, podfile_properties['ios.deploymentTarget'] || '16.4'

prepare_react_native_project!

target 'DigitVACollect' do
  use_expo_modules!

  if ENV['EXPO_USE_COMMUNITY_AUTOLINKING'] == '1'
    config_command = ['node', '-e', "process.argv=['', '', 'config'];require('@react-native-community/cli').run()"];
  end
end
`;

function withEnv(values, run) {
  const saved = { APP_VARIANT: process.env.APP_VARIANT, DIGITVA_IOS_SKIP_ICD11: process.env.DIGITVA_IOS_SKIP_ICD11 };
  try {
    for (const [key, value] of Object.entries(values)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

describe("withIosCollectPlus", () => {
  beforeEach(() => {
    withPodfile.mockClear();
    withDangerousMod.mockClear();
  });

  it("is on only for APP_VARIANT=plus", () => {
    expect(plusBuildRequested({ APP_VARIANT: "plus" })).toBe(true);
    expect(plusBuildRequested({ APP_VARIANT: "development" })).toBe(false);
    expect(plusBuildRequested({})).toBe(false);
  });

  it("excludes both engines in the plain build, ICD-11 only in a SmartVA-only Plus build, none in full Plus", () => {
    expect(excludedModules({})).toEqual(["digitva-icd11", "digitva-smartva"]);
    expect(excludedModules({ APP_VARIANT: "development", DIGITVA_IOS_SKIP_ICD11: "1" })).toEqual(["digitva-icd11", "digitva-smartva"]);
    expect(excludedModules({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: "1" })).toEqual(["digitva-icd11"]);
    expect(excludedModules({ APP_VARIANT: "plus" })).toEqual([]);
  });

  it("adds the exclusion to the bare use_expo_modules! call, once, keeping its indentation", () => {
    const once = patchPodfileExclude(PODFILE, ["digitva-icd11", "digitva-smartva"]);
    expect(once).toContain(
      '  # DigitVA Collect Plus: engine modules excluded from this build\n  use_expo_modules!(exclude: ["digitva-icd11", "digitva-smartva"])\n',
    );
    expect(once).not.toMatch(/^\s*use_expo_modules!\s*$/m);
    expect(patchPodfileExclude(once, ["digitva-icd11", "digitva-smartva"])).toBe(once);
    expect(once.match(/use_expo_modules!/g)).toHaveLength(1);
  });

  it("rewrites an earlier exclusion to the modules of this build", () => {
    const plain = patchPodfileExclude(PODFILE, ["digitva-icd11", "digitva-smartva"]);
    const smartvaOnly = patchPodfileExclude(plain, ["digitva-icd11"]);
    expect(smartvaOnly).toContain('use_expo_modules!(exclude: ["digitva-icd11"])');
    expect(smartvaOnly).not.toContain('"digitva-smartva"');
  });

  it("refuses a Podfile it cannot patch safely", () => {
    expect(() => patchPodfileExclude("target 'App' do\nend\n", ["digitva-icd11"])).toThrow("no bare use_expo_modules!");
    expect(() => patchPodfileExclude("  use_expo_modules!(searchPaths: ['x'])\n", ["digitva-icd11"])).toThrow("no bare use_expo_modules!");
    expect(() => patchPodfileExclude(PODFILE, [])).toThrow("at least one module");
    const broken = `# DigitVA Collect Plus: engine modules excluded from this build\n${PODFILE}`;
    expect(() => patchPodfileExclude(broken, ["digitva-icd11"])).toThrow("existing Plus exclusion is missing");
  });

  it("patches the Podfile and stages nothing in the plain build", () => {
    withEnv({ APP_VARIANT: undefined, DIGITVA_IOS_SKIP_ICD11: undefined }, () => withIosCollectPlus({ name: "DigitVA", slug: "digitva" }));
    expect(withPodfile).toHaveBeenCalledTimes(1);
    expect(withDangerousMod).not.toHaveBeenCalled();
    const [, action] = withPodfile.mock.calls[0];
    expect(action({ modResults: { contents: PODFILE } }).modResults.contents).toContain(
      'use_expo_modules!(exclude: ["digitva-icd11", "digitva-smartva"])',
    );
  });

  it("leaves the Podfile alone and stages before pod install in a full Plus build", () => {
    withEnv({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: undefined }, () => withIosCollectPlus({ name: "DigitVA", slug: "digitva" }));
    expect(withPodfile).not.toHaveBeenCalled();
    expect(withDangerousMod).toHaveBeenCalledTimes(1);
    expect(withDangerousMod.mock.calls[0][1][0]).toBe("ios");
  });

  describe("Plus staging", () => {
    let project;

    beforeEach(() => {
      // A project whose modules hold copies of the real staging scripts, so nothing is staged into this checkout.
      project = fs.mkdtempSync(path.join(os.tmpdir(), "ios-plus-project-"));
      for (const name of ["digitva-smartva", "digitva-icd11"]) {
        const scripts = path.join(project, "modules", name, "scripts");
        fs.mkdirSync(scripts, { recursive: true });
        fs.copyFileSync(path.join(__dirname, "..", "modules", name, "scripts", "stage-engine.js"), path.join(scripts, "stage-engine.js"));
      }
    });

    afterEach(() => fs.rmSync(project, { recursive: true, force: true }));

    function stagingAction(env) {
      withEnv(env, () => withIosCollectPlus({ name: "DigitVA", slug: "digitva" }));
      const [, [, action]] = withDangerousMod.mock.calls[0];
      return () => withEnv(env, () => action({ modRequest: { projectRoot: project } }));
    }

    it("fails the prebuild clearly when the SmartVA xcframework is missing", () => {
      const run = stagingAction({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: "1" });
      expect(run).toThrow("private/generated/smartva-ios/SmartvaRust.xcframework");
    });

    it("stages SmartVA only when ICD-11 is skipped", () => {
      const xcframework = path.join(project, "private", "generated", "smartva-ios", "SmartvaRust.xcframework");
      fs.mkdirSync(xcframework, { recursive: true });
      fs.writeFileSync(path.join(xcframework, "Info.plist"), "<plist/>");
      stagingAction({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: "1" })();
      expect(fs.existsSync(path.join(project, "modules", "digitva-smartva", "ios", "SmartvaRust.xcframework", "Info.plist"))).toBe(true);
      expect(fs.existsSync(path.join(project, "modules", "digitva-icd11", "ios"))).toBe(false);
    });

    it("fails clearly when ICD-11 is wanted and its iOS engine is missing", () => {
      const xcframework = path.join(project, "private", "generated", "smartva-ios", "SmartvaRust.xcframework");
      fs.mkdirSync(xcframework, { recursive: true });
      fs.writeFileSync(path.join(xcframework, "Info.plist"), "<plist/>");
      const run = stagingAction({ APP_VARIANT: "plus", DIGITVA_IOS_SKIP_ICD11: undefined });
      expect(run).toThrow("DIGITVA_IOS_SKIP_ICD11=1");
    });
  });
});
