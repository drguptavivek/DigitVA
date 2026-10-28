import { createOfflineSmartvaEngine, type NativeSmartvaModule } from "../src/smartva/nativeEngine";
import type { SmartVaRequest } from "../src/smartva/contracts";

const request: SmartVaRequest = {
  schema_version: 1,
  input: { sid: "synthetic", id1: "1" },
  options: { country: "IND", hiv: true, malaria: true, hce: true, freetext: true },
};

function processError() {
  return Object.assign(new Error("process stopped"), { code: "ERR_SMARTVA_PROCESS" });
}

function native(overrides: Partial<NativeSmartvaModule> = {}): NativeSmartvaModule {
  return {
    isAvailable: jest.fn(async () => true),
    init: jest.fn(async () => ({ ok: true, version: "test", ms: 1 })),
    score: jest.fn(async () => ({ ok: true, text: '{"total_vas":1,"predictions":[]}', nativeMs: 2, version: "test" })),
    ...overrides,
  };
}

describe("offline SmartVA native adapter", () => {
  it("does not initialize during availability checks and blocks init/score while disabled", async () => {
    const bridge = native();
    const engine = createOfflineSmartvaEngine(bridge, async () => false);

    expect(await engine.available()).toBe(true);
    expect(bridge.init).not.toHaveBeenCalled();
    expect(await engine.init()).toMatchObject({ ok: false, error: "icd11_doris_disabled" });
    expect(await engine.score(request)).toMatchObject({ ok: false, error: "icd11_doris_disabled" });
    expect(bridge.init).not.toHaveBeenCalled();
    expect(bridge.score).not.toHaveBeenCalled();
  });

  it("lazily initializes only when a case is scored, and passes the fixed JSON request through", async () => {
    const bridge = native();
    const engine = createOfflineSmartvaEngine(bridge, async () => true);

    expect(bridge.init).not.toHaveBeenCalled();
    const result = await engine.score(request);

    expect(result).toMatchObject({ ok: true, nativeMs: 2, version: "test" });
    expect(bridge.init).toHaveBeenCalledTimes(1);
    expect(bridge.score).toHaveBeenCalledWith(JSON.stringify(request));
  });

  it("rebinds and retries once after native process death without exposing its error text", async () => {
    const bridge = native({
      score: jest.fn()
        .mockRejectedValueOnce(processError())
        .mockResolvedValueOnce({ ok: true, text: "{}", nativeMs: 3, version: "test" }),
    });
    const engine = createOfflineSmartvaEngine(bridge, async () => true);

    expect(await engine.score(request)).toMatchObject({ ok: true, text: "{}" });
    expect(bridge.init).toHaveBeenCalledTimes(2);
    expect(bridge.score).toHaveBeenCalledTimes(2);
  });

  it("does not retry ordinary native errors or expose the exception message", async () => {
    const bridge = native({ score: jest.fn().mockRejectedValue(new Error("sensitive input detail")) });
    const engine = createOfflineSmartvaEngine(bridge, async () => true);

    expect(await engine.score(request)).toMatchObject({ ok: false, error: "native_error" });
    expect(bridge.score).toHaveBeenCalledTimes(1);
    expect(bridge.init).toHaveBeenCalledTimes(1);
  });
});
