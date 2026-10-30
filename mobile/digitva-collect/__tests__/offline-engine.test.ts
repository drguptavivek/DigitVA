import { InteractionManager } from "react-native";

import type { NativeEngine } from "../src/offlineEngine";
let mockIcd11Enabled = false;
let mockNativeModule: NativeEngine | null = null;
jest.mock("../src/icd11DorisPreference", () => ({ isIcd11DorisEnabled: async () => mockIcd11Enabled }));
jest.mock("expo", () => ({ requireOptionalNativeModule: () => mockNativeModule }));

import { afterInteractionsOrTimeout, createOfflineEngine, offlineEngine, scheduleEngineWarmUp, warmUpOfflineEngine } from "../src/offlineEngine";
import { CHECK_CERTIFICATE, runEngineCheck } from "../src/offlineEngineCheck";

function fakeNative(overrides: Partial<NativeEngine> = {}): NativeEngine {
  return {
    isAvailable: async () => true,
    init: async () => ({ ok: true, copyMs: 5, initMs: 20, ms: 26, cached: false }),
    updateWhoFiles: async () => ({ ok: false, error: "no_connection", copyMs: 0, initMs: 0, ms: 0, cached: false }),
    call: async (op) => ({ ok: true, status: 200, text: JSON.stringify({ op, destinationEntities: [1, 2], code: "BC42.Z" }), nativeMs: 3 }),
    ...overrides,
  };
}

/** A clock that advances 10 ms per read, so a wrapped call reports 10. */
function steppingClock() {
  let t = 0;
  return () => (t += 10);
}

describe("offlineEngine without the native module (plain build, web)", () => {
  const engine = createOfflineEngine(null);

  it("reports unavailable and never throws", async () => {
    expect(await engine.available()).toBe(false);
    expect(await engine.init()).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.search("x")).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.codeinfo("BA41.Z")).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.doris({})).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.codedit({})).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.entity("1334938734")).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.foundationEntity("1334938734")).toEqual({ ok: false, error: "unavailable", ms: 0 });
    expect(await engine.call("search", { q: "x" })).toEqual({ ok: false, error: "unavailable", ms: 0 });
  });

  it("makes the check stop at the first step", async () => {
    const steps = await runEngineCheck(engine);
    expect(steps).toEqual([{ name: "available", ok: false, ms: 0, note: "unavailable" }]);
  });
});

describe("offlineEngine with a native module", () => {
  it("returns parsed data with the round trip and the engine time", async () => {
    const engine = createOfflineEngine(fakeNative(), steppingClock());
    const result = await engine.search("myocardial infarction");
    expect(result).toMatchObject({ ok: true, status: 200, ms: 10, nativeMs: 3 });
    expect((result as { data: { op: string } }).data.op).toBe("search");
  });

  it("sends a certificate as the `certificate` argument", async () => {
    const call = jest.fn(fakeNative().call);
    const engine = createOfflineEngine(fakeNative({ call }));
    await engine.doris(CHECK_CERTIFICATE);
    await engine.codedit(CHECK_CERTIFICATE);
    expect(call).toHaveBeenNthCalledWith(1, "doris", JSON.stringify({ certificate: CHECK_CERTIFICATE }));
    expect(call).toHaveBeenNthCalledWith(2, "codedit", JSON.stringify({ certificate: CHECK_CERTIFICATE }));
  });

  it("sends each op's named arguments as one JSON object and leaves out options that are not set", async () => {
    const call = jest.fn(fakeNative().call);
    const engine = createOfflineEngine(fakeNative({ call }));
    await engine.search("heart");
    await engine.search("heart%", { subtreesFilter: "http://id.who.int/icd/release/11/2026-01/mms/979408586", medicalCodingMode: true, chapterFilter: undefined });
    await engine.codeinfo("BA41.Z");
    await engine.codeinfo("BA41.Z", { flexiblemode: true });
    await engine.entity("1334938734");
    await engine.entity("1334938734", { residual: "unspecified", include: "ancestor" });
    await engine.foundationEntity("1334938734", { include: "diagnosticCriteria" });
    await engine.search("heart%", { limit: 20 });
    await engine.call("search", { q: "x" });
    expect(call.mock.calls).toEqual([
      ["search", '{"q":"heart"}'],
      ["search", '{"q":"heart%","subtreesFilter":"http://id.who.int/icd/release/11/2026-01/mms/979408586","medicalCodingMode":true}'],
      ["codeinfo", '{"code":"BA41.Z"}'],
      ["codeinfo", '{"code":"BA41.Z","flexiblemode":true}'],
      ["entity", '{"id":"1334938734"}'],
      ["entity", '{"id":"1334938734","residual":"unspecified","include":"ancestor"}'],
      ["foundation_entity", '{"id":"1334938734","include":"diagnosticCriteria"}'],
      ["search", '{"q":"heart%","limit":20}'],
      ["search", '{"q":"x"}'],
    ]);
  });

  it("returns the parsed WHO reply of an entity call", async () => {
    const native = fakeNative({ call: async () => ({ ok: true, status: 200, text: JSON.stringify({ "@id": "http://id.who.int/icd/release/11/2026-01/mms/1334938734", title: { "@value": "Acute myocardial infarction" } }), nativeMs: 2 }) });
    const result = await createOfflineEngine(native).entity("1334938734");
    expect(result).toMatchObject({ ok: true, status: 200, data: { title: { "@value": "Acute myocardial infarction" } } });
  });

  it("times init and passes the split through", async () => {
    const result = await createOfflineEngine(fakeNative(), steppingClock()).init();
    expect(result).toEqual({ ok: true, ms: 10, copyMs: 5, initMs: 20, cached: false });
  });

  it("keeps a sticky init failure's code and drops anything else", async () => {
    const engine = createOfflineEngine(fakeNative({ init: async () => ({ ok: false, error: "init_failed", copyMs: 1, initMs: 2, ms: 3, cached: false }) }));
    expect(await engine.init()).toMatchObject({ ok: false, error: "init_failed" });
  });

  it("reports a failed call by status, with no body", async () => {
    const engine = createOfflineEngine(fakeNative({ call: async () => ({ ok: false, error: "engine_status", status: 500, nativeMs: 1 }) }));
    const result = await engine.codeinfo("ZZ");
    expect(result).toMatchObject({ ok: false, error: "engine_status", status: 500 });
    expect(result).not.toHaveProperty("data");
  });

  it("turns unparseable text and native rejections into codes, not messages", async () => {
    const badJson = createOfflineEngine(fakeNative({ call: async () => ({ ok: true, status: 200, text: "{not json", nativeMs: 1 }) }));
    expect(await badJson.search("x")).toMatchObject({ ok: false, error: "bad_json" });
    const rejecting = createOfflineEngine(fakeNative({ call: async () => { throw new Error("stack with certificate text"); } }));
    const result = await rejecting.search("x");
    expect(result).toMatchObject({ ok: false, error: "native_error" });
    expect(JSON.stringify(result)).not.toContain("certificate");
  });

  it("runs the whole check and stops after a failed init", async () => {
    const steps = await runEngineCheck(createOfflineEngine(fakeNative()));
    expect(steps.map((step) => step.name)).toEqual(["init", "search", "codeinfo BC42.Z", "doris", "doris (warm)", "codedit"]);
    expect(steps.every((step) => step.ok)).toBe(true);
    expect(steps.find((step) => step.name === "doris")?.note).toBe("underlying BC42.Z");
    const pascal = await runEngineCheck(createOfflineEngine(fakeNative({ call: async () => ({ ok: true, status: 200, text: JSON.stringify({ Code: "BA41.Z" }), nativeMs: 1 }) })));
    expect(pascal.find((step) => step.name === "doris")?.note).toBe("underlying ?"); // the engine writes camelCase; PascalCase is not read
    const failed = await runEngineCheck(createOfflineEngine(fakeNative({ init: async () => ({ ok: false, error: "load_failed", copyMs: 0, initMs: 0, ms: 1, cached: false }) })));
    expect(failed.map((step) => step.name)).toEqual(["init"]);
    expect(failed[0]).toMatchObject({ ok: false, note: "load_failed" });
  });
});

it("keeps the production engine inert while the device ICD-11 preference is off", async () => {
  const init = jest.fn(fakeNative().init);
  const call = jest.fn(fakeNative().call);
  mockNativeModule = fakeNative({ init, call });
  mockIcd11Enabled = false;
  const engine = offlineEngine();

  expect(await engine.init()).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(await engine.search("BC42.Z")).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(await engine.entity("1334938734")).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(await engine.foundationEntity("1334938734")).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(await engine.call("search", { q: "x" })).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(await engine.updateWhoFiles()).toEqual({ ok: false, error: "icd11_doris_disabled", ms: 0 });
  expect(init).not.toHaveBeenCalled();
  expect(call).not.toHaveBeenCalled();
});

describe("offlineEngine start-up sharing and recovery", () => {
  function deferredInit() {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const init = jest.fn(async () => {
      await gate;
      return { ok: true, copyMs: 1, initMs: 2, ms: 3, cached: false, phases: "config=1 index=2" };
    });
    return { init, release };
  }

  it("shares one in-flight init between the warm-up and a later caller", async () => {
    const { init, release } = deferredInit();
    const engine = createOfflineEngine(fakeNative({ init }));
    const first = engine.init();
    const second = engine.init();
    release();
    expect(await first).toMatchObject({ ok: true, cached: false, phases: "config=1 index=2" });
    expect(await second).toEqual(await first);
    expect(init).toHaveBeenCalledTimes(1);
  });

  it("answers an init after success as cached without asking the native side again", async () => {
    const init = jest.fn(fakeNative().init);
    const engine = createOfflineEngine(fakeNative({ init }));
    await engine.init();
    expect(await engine.init()).toMatchObject({ ok: true, ms: 0, cached: true });
    expect(init).toHaveBeenCalledTimes(1);
  });

  it("lets a failed init be tried again", async () => {
    const init = jest
      .fn<ReturnType<NativeEngine["init"]>, []>()
      .mockResolvedValueOnce({ ok: false, error: "init_failed", copyMs: 0, initMs: 0, ms: 1, cached: false })
      .mockResolvedValueOnce({ ok: true, copyMs: 0, initMs: 1, ms: 1, cached: false });
    const engine = createOfflineEngine(fakeNative({ init }));
    expect(await engine.init()).toMatchObject({ ok: false, error: "init_failed" });
    expect(await engine.init()).toMatchObject({ ok: true });
  });

  it("re-inits once and retries when Android killed the engine process", async () => {
    const init = jest.fn(fakeNative().init);
    const call = jest
      .fn<ReturnType<NativeEngine["call"]>, Parameters<NativeEngine["call"]>>()
      .mockResolvedValueOnce({ ok: false, error: "not_initialized", status: 503, nativeMs: 0 })
      .mockResolvedValue({ ok: true, status: 200, text: "{\"code\":\"BC42.Z\"}", nativeMs: 1 });
    const engine = createOfflineEngine(fakeNative({ init, call }));
    await engine.init();
    expect(await engine.codeinfo("BC42.Z")).toMatchObject({ ok: true, data: { code: "BC42.Z" } });
    expect(init).toHaveBeenCalledTimes(2);
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("retries after a rejected call from a lost process, but not for other rejections", async () => {
    const lost = Object.assign(new Error("engine process stopped"), { code: "ERR_ICD11_PROCESS" });
    const call = jest
      .fn<ReturnType<NativeEngine["call"]>, Parameters<NativeEngine["call"]>>()
      .mockRejectedValueOnce(lost)
      .mockResolvedValue({ ok: true, status: 200, text: "{}", nativeMs: 1 });
    const engine = createOfflineEngine(fakeNative({ call }));
    await engine.init();
    expect(await engine.search("x")).toMatchObject({ ok: true });
    const other = createOfflineEngine(fakeNative({ call: jest.fn().mockRejectedValue(new Error("boom")) }));
    await other.init();
    expect(await other.search("x")).toMatchObject({ ok: false, error: "native_error" });
  });

  it("a call made while an init is in flight waits for it before reaching the engine", async () => {
    let finishInit!: () => void;
    const init = jest.fn(() => new Promise<Awaited<ReturnType<NativeEngine["init"]>>>((resolve) => {
      finishInit = () => resolve({ ok: true, copyMs: 0, initMs: 1, ms: 1, cached: false });
    }));
    const call = jest.fn(fakeNative().call);
    const engine = createOfflineEngine(fakeNative({ init, call }));
    const pendingInit = engine.init();
    const pendingSearch = engine.search("x");
    await Promise.resolve();
    expect(init).toHaveBeenCalledTimes(1);
    expect(call).not.toHaveBeenCalled();
    finishInit();
    await pendingInit;
    expect(await pendingSearch).toMatchObject({ ok: true });
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("does not retry a call that never had an init", async () => {
    const call = jest.fn(async () => ({ ok: false, error: "not_initialized", status: 503, nativeMs: 0 }));
    const init = jest.fn(fakeNative().init);
    const result = await createOfflineEngine(fakeNative({ call, init })).search("x");
    expect(result).toMatchObject({ ok: false, error: "not_initialized" });
    expect(init).not.toHaveBeenCalled();
  });

  it("warms up once, logging timings only, and skips an unavailable engine", async () => {
    const log = jest.fn();
    await warmUpOfflineEngine(createOfflineEngine(fakeNative()), log);
    expect(log).toHaveBeenCalledTimes(1);
    expect(log.mock.calls[0][0]).toMatch(/^ICD11WARM ready=true ms=\d+ cached=false at=\d+$/);
    const none = jest.fn();
    await warmUpOfflineEngine(createOfflineEngine(null), none);
    await warmUpOfflineEngine(createOfflineEngine(fakeNative({ isAvailable: async () => false })), none);
    expect(none).not.toHaveBeenCalled();
  });

  it("re-checks a ready engine with the native side, which restarts only a lost process", async () => {
    let alive = false;
    const init = jest.fn(async () => {
      const cached = alive;
      alive = true;
      return { ok: true, copyMs: 0, initMs: cached ? 0 : 20, ms: cached ? 0 : 26, cached };
    });
    const engine = createOfflineEngine(fakeNative({ init }));
    expect(await engine.warm()).toMatchObject({ ok: true, cached: false });
    // Warm and alive: the native side answers cached; init() alone never reaches native.
    expect(await engine.warm()).toMatchObject({ ok: true, cached: true });
    await engine.init();
    expect(init).toHaveBeenCalledTimes(2);
    // Android ended the engine process: the next warm-up starts a new one.
    alive = false;
    expect(await engine.warm()).toMatchObject({ ok: true, cached: false });
    // A warm-up during an init shares it.
    alive = false;
    await Promise.all([engine.warm(), engine.warm()]);
    expect(init).toHaveBeenCalledTimes(4);
  });

  it("schedules the warm-up after interactions and the delay, and can be cancelled before it starts", async () => {
    jest.useFakeTimers();
    try {
      const init = jest.fn(fakeNative().init);
      let task: () => void = () => undefined;
      const cancel = jest.fn();
      const stop = scheduleEngineWarmUp(createOfflineEngine(fakeNative({ init })), 500, (fn) => ((task = fn), { cancel }));
      jest.advanceTimersByTime(10_000);
      expect(init).not.toHaveBeenCalled();
      task();
      jest.advanceTimersByTime(499);
      expect(init).not.toHaveBeenCalled();
      stop();
      expect(cancel).toHaveBeenCalled();
      jest.advanceTimersByTime(10_000);
      await Promise.resolve();
      expect(init).not.toHaveBeenCalled();

      const run = scheduleEngineWarmUp(createOfflineEngine(fakeNative({ init })), 500, (fn) => ((task = fn), { cancel }));
      task();
      jest.advanceTimersByTime(500);
      await jest.advanceTimersByTimeAsync(0);
      expect(init).toHaveBeenCalledTimes(1);
      run();
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("afterInteractionsOrTimeout", () => {
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("runs the task after the fallback when interactions never settle (a looping spinner)", () => {
    jest.useFakeTimers();
    const cancel = jest.fn();
    jest.spyOn(InteractionManager, "runAfterInteractions").mockReturnValue({ cancel } as never);
    const task = jest.fn();
    afterInteractionsOrTimeout(task, 5000);
    jest.advanceTimersByTime(4999);
    expect(task).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it("runs once when interactions settle first, and not again at the fallback", () => {
    jest.useFakeTimers();
    let settle!: () => void;
    jest.spyOn(InteractionManager, "runAfterInteractions").mockImplementation(((fn: () => void) => {
      settle = fn;
      return { cancel: jest.fn() };
    }) as never);
    const task = jest.fn();
    afterInteractionsOrTimeout(task, 5000);
    settle();
    expect(task).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(5000);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it("cancel stops both paths", () => {
    jest.useFakeTimers();
    jest.spyOn(InteractionManager, "runAfterInteractions").mockReturnValue({ cancel: jest.fn() } as never);
    const task = jest.fn();
    afterInteractionsOrTimeout(task, 5000).cancel();
    jest.advanceTimersByTime(6000);
    expect(task).not.toHaveBeenCalled();
  });
});
