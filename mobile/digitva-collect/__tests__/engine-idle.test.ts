const mockModules: Record<string, unknown> = {};
jest.mock("expo", () => ({ requireOptionalNativeModule: (name: string) => mockModules[name] ?? null }));
jest.mock("expo-router", () => ({ useFocusEffect: () => undefined }));
jest.mock("../src/icd11DorisPreference", () => ({ isIcd11DorisEnabled: async () => true }));

import { createEngineIdle, releaseEngines } from "../src/engineIdle";
import { createOfflineEngine, type NativeEngine } from "../src/offlineEngine";
import { createOfflineSmartvaEngine, type NativeSmartvaModule } from "../src/smartva/nativeEngine";

const IDLE = 1000;
const RETRY = 100;

/** Lets the release promise chain settle under fake timers. */
const flush = async () => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

describe("engine idle manager", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("releases only after the last coding screen blurs and the idle time passes", async () => {
    const release = jest.fn(async () => true);
    const idle = createEngineIdle(release, IDLE, RETRY);
    const blurA = idle.focus();
    const blurB = idle.focus();
    blurA();
    jest.advanceTimersByTime(IDLE * 2);
    expect(release).not.toHaveBeenCalled();
    blurB();
    jest.advanceTimersByTime(IDLE - 1);
    expect(release).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    await flush();
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("cancels the countdown on refocus, and a repeated blur counts once", () => {
    const release = jest.fn(async () => true);
    const idle = createEngineIdle(release, IDLE, RETRY);
    const blur = idle.focus();
    blur();
    jest.advanceTimersByTime(IDLE - 1);
    const blurAgain = idle.focus();
    blur();
    jest.advanceTimersByTime(IDLE * 2);
    expect(release).not.toHaveBeenCalled();
    blurAgain();
    jest.advanceTimersByTime(IDLE);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("retries a refused release until it succeeds, and not after a refocus", async () => {
    const release = jest.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(false).mockResolvedValue(true);
    const idle = createEngineIdle(release, IDLE, RETRY);
    idle.focus()();
    jest.advanceTimersByTime(IDLE);
    await flush();
    jest.advanceTimersByTime(RETRY);
    await flush();
    expect(release).toHaveBeenCalledTimes(2);
    const blur = idle.focus();
    jest.advanceTimersByTime(RETRY * 10);
    await flush();
    expect(release).toHaveBeenCalledTimes(2);
    blur();
    jest.advanceTimersByTime(IDLE);
    await flush();
    expect(release).toHaveBeenCalledTimes(3);
    jest.advanceTimersByTime(RETRY * 10);
    expect(release).toHaveBeenCalledTimes(3);
  });

  it("treats a rejected release as refused", async () => {
    const release = jest.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue(true);
    const idle = createEngineIdle(release, IDLE, RETRY);
    idle.focus()();
    jest.advanceTimersByTime(IDLE);
    await flush();
    jest.advanceTimersByTime(RETRY);
    expect(release).toHaveBeenCalledTimes(2);
  });
});

function icdNative(overrides: Partial<NativeEngine> = {}): NativeEngine {
  return {
    isAvailable: jest.fn(async () => true),
    init: jest.fn(async () => ({ ok: true, copyMs: 0, initMs: 1, ms: 1, cached: false })),
    updateWhoFiles: jest.fn(),
    call: jest.fn(async () => ({ ok: true, status: 200, text: "{}", nativeMs: 1 })),
    ...overrides,
  } as NativeEngine;
}

function smartvaNative(overrides: Partial<NativeSmartvaModule> = {}): NativeSmartvaModule {
  return {
    isAvailable: jest.fn(async () => true),
    init: jest.fn(async () => ({ ok: true, version: "v" })),
    score: jest.fn(),
    ...overrides,
  };
}

describe("engine release", () => {
  it("ICD: releases through native and inits again on next use", async () => {
    const native = icdNative({ release: jest.fn(async () => true) });
    const engine = createOfflineEngine(native);
    await engine.init();
    expect(await engine.release!()).toBe(true);
    expect(native.release).toHaveBeenCalledTimes(1);
    expect((await engine.init()).ok).toBe(true);
    expect(native.init).toHaveBeenCalledTimes(2);
  });

  it("ICD: refuses while an init is pending, and keeps ready when native refuses", async () => {
    let finish!: () => void;
    const native = icdNative({
      init: jest.fn(() => new Promise((resolve) => { finish = () => resolve({ ok: true, copyMs: 0, initMs: 1, ms: 1, cached: false }); })),
      release: jest.fn(async () => false),
    });
    const engine = createOfflineEngine(native);
    const init = engine.init();
    expect(await engine.release!()).toBe(false);
    expect(native.release).not.toHaveBeenCalled();
    finish();
    await init;
    expect(await engine.release!()).toBe(false);
    expect(await engine.init()).toMatchObject({ ok: true, cached: true });
  });

  it("ICD and SmartVA: a native module without release (iOS before this, older builds) counts as released", async () => {
    expect(await createOfflineEngine(icdNative()).release!()).toBe(true);
    expect(await createOfflineSmartvaEngine(smartvaNative(), async () => true).release!()).toBe(true);
  });

  it("SmartVA: releases through native and inits again on next use", async () => {
    const native = smartvaNative({ release: jest.fn(async () => true) });
    const engine = createOfflineSmartvaEngine(native, async () => true);
    await engine.init();
    expect(await engine.release!()).toBe(true);
    await engine.init();
    expect(native.init).toHaveBeenCalledTimes(2);
  });
});

describe("releaseEngines", () => {
  it("releases both engines and reports a refusal from either", async () => {
    const icdRelease = jest.fn(async () => true);
    const smartvaRelease = jest.fn(async () => false);
    mockModules.DigitvaIcd11 = icdNative({ release: icdRelease });
    mockModules.DigitvaSmartva = smartvaNative({ release: smartvaRelease });
    expect(await releaseEngines()).toBe(false);
    expect(icdRelease).toHaveBeenCalledTimes(1);
    expect(smartvaRelease).toHaveBeenCalledTimes(1);
    smartvaRelease.mockResolvedValue(true);
    expect(await releaseEngines()).toBe(true);
  });
});
