import { createOfflineEngine, type NativeEngine } from "../src/offlineEngine";
import { CHECK_CERTIFICATE, runEngineCheck } from "../src/offlineEngineCheck";

function fakeNative(overrides: Partial<NativeEngine> = {}): NativeEngine {
  return {
    isAvailable: async () => true,
    init: async () => ({ ok: true, copyMs: 5, initMs: 20, ms: 26, cached: false }),
    call: async (op) => ({ ok: true, status: 200, text: JSON.stringify({ op, destinationEntities: [1, 2], code: "BC42.Z", Code: "BA41.Z" }), nativeMs: 3 }),
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

  it("sends a certificate as JSON text", async () => {
    const call = jest.fn(fakeNative().call);
    await createOfflineEngine(fakeNative({ call })).doris(CHECK_CERTIFICATE);
    expect(call).toHaveBeenCalledWith("doris", JSON.stringify(CHECK_CERTIFICATE));
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
    expect(steps.find((step) => step.name === "doris")?.note).toBe("underlying BA41.Z");
    const failed = await runEngineCheck(createOfflineEngine(fakeNative({ init: async () => ({ ok: false, error: "load_failed", copyMs: 0, initMs: 0, ms: 1, cached: false }) })));
    expect(failed.map((step) => step.name)).toEqual(["init"]);
    expect(failed[0]).toMatchObject({ ok: false, note: "load_failed" });
  });
});
