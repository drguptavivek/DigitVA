import { createOfflineEngine, parseSetup, type NativeEngine, type NativeInit } from "../src/offlineEngine";
import { describeProgress, describeSetup, runEngineCheck } from "../src/offlineEngineCheck";

type ProgressListener = Parameters<NonNullable<NativeEngine["addListener"]>>[1];

const SHIPPED: NativeInit = { ok: true, copyMs: 1, initMs: 2, ms: 3, cached: false, setup: JSON.stringify({ mode: "shipped", files: [] }) };

/** A native module whose progress events the test emits by hand. */
function nativeWithProgress(
  init: NativeEngine["init"] = async () => ({ ok: true, copyMs: 1, initMs: 2, ms: 3, cached: false }),
  updateWhoFiles: NativeEngine["updateWhoFiles"] = async () => SHIPPED
) {
  let listener: ProgressListener = () => undefined;
  const native: NativeEngine = {
    isAvailable: async () => true,
    init,
    updateWhoFiles,
    call: async () => ({ ok: true, status: 200, text: "{}", nativeMs: 1 }),
    addListener: (_event, next) => {
      listener = next;
      return { remove: () => undefined };
    },
  };
  return { native, emit: (phase: string, percent: number) => listener({ phase, percent }) };
}

describe("engine progress", () => {
  it("passes each report to every listener, with an unknown percent as undefined", () => {
    const { native, emit } = nativeWithProgress();
    const engine = createOfflineEngine(native);
    const seen: unknown[] = [];
    const other: unknown[] = [];
    engine.onProgress((progress) => seen.push(progress));
    engine.onProgress((progress) => other.push(progress));
    emit("copy", 40);
    emit("setup", -1);
    expect(seen).toEqual([
      { phase: "copy", percent: 40 },
      { phase: "setup", percent: undefined },
    ]);
    expect(other).toEqual(seen);
  });

  it("stops calling a listener after it unsubscribes", () => {
    const { native, emit } = nativeWithProgress();
    const engine = createOfflineEngine(native);
    const listener = jest.fn();
    const stop = engine.onProgress(listener);
    emit("copy", 10);
    stop();
    emit("copy", 20);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("has no progress without a native module, and works with one that cannot listen", () => {
    expect(createOfflineEngine(null).onProgress(() => undefined)).toEqual(expect.any(Function));
    const engine = createOfflineEngine({ ...nativeWithProgress().native, addListener: undefined });
    const listener = jest.fn();
    engine.onProgress(listener);
    expect(listener).not.toHaveBeenCalled();
  });

  it("describes a report for the screen, with the percent only when known", () => {
    expect(describeProgress({ phase: "copy", percent: 40 })).toBe("copy 40%");
    expect(describeProgress({ phase: "setup", percent: undefined })).toBe("setup");
  });
});

describe("first-setup record", () => {
  it("parses a downloaded record and keeps only the fields the check shows", () => {
    const text = JSON.stringify({ mode: "downloaded", files: [{ path: "data/DORIS/rules.xml", size: 12, sha256: "ab" }] });
    expect(parseSetup(text)).toEqual({ mode: "downloaded", files: [{ path: "data/DORIS/rules.xml", size: 12 }] });
  });

  it("reads anything unexpected as no record", () => {
    expect(parseSetup(undefined)).toBeUndefined();
    expect(parseSetup("")).toBeUndefined();
    expect(parseSetup("{not json")).toBeUndefined();
    expect(parseSetup(JSON.stringify({ files: [] }))).toBeUndefined();
    expect(parseSetup(JSON.stringify({ mode: "shipped", files: "x" }))).toBeUndefined();
  });

  it("drops file entries that lack a path or a size", () => {
    const text = JSON.stringify({ mode: "downloaded", files: [{ path: "a", size: 1 }, { path: 3, size: 1 }, { size: 2 }, null] });
    expect(parseSetup(text)).toEqual({ mode: "downloaded", files: [{ path: "a", size: 1 }] });
  });

  it("describes a setup that changed WHO files with them, and one that changed none as shipped copies", () => {
    expect(describeSetup({ mode: "downloaded", files: [{ path: "a.xml", size: 5 }, { path: "b.zip", size: 9 }] })).toBe(
      "downloaded 2 files: a.xml (5 B); b.zip (9 B)"
    );
    expect(describeSetup({ mode: "downloaded", files: [] })).toBe("shipped copies (no newer WHO files)");
    expect(describeSetup({ mode: "shipped", files: [] })).toBe("shipped copies (no newer WHO files)");
  });

  it("lists only the WHO files the record names, never engine-built ones", () => {
    const text = JSON.stringify({ mode: "downloaded", files: [{ path: "data/DORIS_v2.1_1.2.0/Rules.json", size: 1, sha256: "a" }] });
    expect(describeSetup(parseSetup(text)!)).toBe("downloaded 1 files: data/DORIS_v2.1_1.2.0/Rules.json (1 B)");
  });

  it("adds a setup step to the check, after init, when init reports one", async () => {
    const setup = JSON.stringify({ mode: "shipped", files: [] });
    const steps = await runEngineCheck(
      createOfflineEngine(nativeWithProgress(async () => ({ ok: true, copyMs: 1, initMs: 2, ms: 3, cached: false, setup })).native)
    );
    expect(steps.map((step) => step.name)).toEqual(["init", "setup", "search", "codeinfo BC42.Z", "doris", "doris (warm)", "codedit"]);
    expect(steps[1]).toMatchObject({ ok: true, note: "shipped copies (no newer WHO files)" });
  });

  it("keeps the check without a setup step when init reports none", async () => {
    const steps = await runEngineCheck(createOfflineEngine(nativeWithProgress().native));
    expect(steps.map((step) => step.name)).not.toContain("setup");
  });
});

describe("explicit WHO-file update", () => {
  it("runs one update in the engine and then serves init from it, without a second native init", async () => {
    const updated: NativeInit = { ...SHIPPED, setup: JSON.stringify({ mode: "downloaded", files: [{ path: "x", size: 2, sha256: "a" }] }) };
    const updateWhoFiles = jest.fn(async (): Promise<NativeInit> => updated);
    const init = jest.fn(async (): Promise<NativeInit> => SHIPPED);
    const engine = createOfflineEngine(nativeWithProgress(init, updateWhoFiles).native);
    const result = await engine.updateWhoFiles();
    expect(result).toMatchObject({ ok: true, setup: { mode: "downloaded", files: [{ path: "x", size: 2 }] } });
    expect(await engine.init()).toMatchObject({ ok: true, cached: true });
    expect(updateWhoFiles).toHaveBeenCalledTimes(1);
    expect(init).not.toHaveBeenCalled();
  });

  it("reports no connection and leaves the next init to run as usual", async () => {
    const init = jest.fn(async (): Promise<NativeInit> => SHIPPED);
    const offline = async (): Promise<NativeInit> => ({ ok: false, error: "no_connection", copyMs: 0, initMs: 0, ms: 0, cached: false });
    const engine = createOfflineEngine(nativeWithProgress(init, offline).native);
    expect(await engine.updateWhoFiles()).toMatchObject({ ok: false, error: "no_connection" });
    expect(await engine.init()).toMatchObject({ ok: true });
    expect(init).toHaveBeenCalledTimes(1);
  });

  it("turns a rejected update into native_error, never a throw", async () => {
    const engine = createOfflineEngine(
      nativeWithProgress(undefined, async () => {
        throw new Error("process gone");
      }).native
    );
    expect(await engine.updateWhoFiles()).toMatchObject({ ok: false, error: "native_error" });
  });

  it("makes an interactive call wait for the update in progress", async () => {
    let finishUpdate: (value: NativeInit) => void = () => undefined;
    const call = jest.fn(async (): Promise<Awaited<ReturnType<NativeEngine["call"]>>> => ({ ok: true, status: 200, text: '{"code":"BC42.Z"}', nativeMs: 1 }));
    const native: NativeEngine = {
      ...nativeWithProgress().native,
      call,
      updateWhoFiles: () => new Promise<NativeInit>((resolve) => (finishUpdate = resolve)),
    };
    const engine = createOfflineEngine(native);
    const update = engine.updateWhoFiles();
    const search = engine.codeinfo("BC42.Z");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(call).not.toHaveBeenCalled();
    finishUpdate(SHIPPED);
    expect(await update).toMatchObject({ ok: true });
    expect(await search).toMatchObject({ ok: true, data: { code: "BC42.Z" } });
    expect(call).toHaveBeenCalledTimes(1);
  });
});
