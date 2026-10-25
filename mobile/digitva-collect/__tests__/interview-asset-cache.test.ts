import {
  setInterviewAssetWarmEligibility,
  warmInterviewAssetsNow,
} from "../src/web/interviewAssetCache";

describe("post-login WHO interview asset cache", () => {
  let idle!: () => void;
  let connectionChange!: () => void;
  const messages: unknown[] = [];
  const addEventListener = jest.fn();

  beforeEach(() => {
    messages.length = 0;
    idle = undefined as unknown as () => void;
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: {
        visibilityState: "visible",
        addEventListener,
        removeEventListener: jest.fn(),
      },
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: {
        onLine: true,
        connection: {
          effectiveType: "3g", saveData: false,
          addEventListener: (_type: "change", listener: () => void) => { connectionChange = listener; },
        },
        serviceWorker: {
          ready: Promise.resolve({
            active: { postMessage: (message: unknown) => messages.push(message) },
          }),
        },
      },
    });
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        isSecureContext: true,
        __DIGITVA_WEB_RELEASE__: "release",
        addEventListener,
        removeEventListener: jest.fn(),
        requestIdleCallback: (callback: () => void) => {
          idle = callback;
          return 1;
        },
        cancelIdleCallback: jest.fn(),
        clearTimeout: jest.fn(),
        setTimeout: jest.fn(),
      },
    });
  });

  it("does not warm anonymous/coder-only sessions, then warms eligible interview access and cancels it", async () => {
    setInterviewAssetWarmEligibility(false);
    await Promise.resolve();
    expect(messages.filter((message: any) => message.type === "warm-interview-assets")).toEqual([]);

    // Unknown/slow connections are automatic-warm blockers.
    setInterviewAssetWarmEligibility(true);
    expect(idle).toBeUndefined();

    (navigator as Navigator & { connection: { effectiveType: string; saveData: boolean } }).connection = {
      effectiveType: "4g", saveData: false,
    };
    setInterviewAssetWarmEligibility(true);
    idle();
    await Promise.resolve();
    expect(messages.filter((message: any) => message.type === "warm-interview-assets")).toEqual([expect.objectContaining({
      type: "warm-interview-assets", group: "interviewRuntime", release: "release",
    })]);

    // Automatic warming is cancelled immediately when a good connection downgrades.
    (navigator as Navigator & { connection: { effectiveType: string; saveData: boolean } }).connection.effectiveType = "3g";
    connectionChange();
    await Promise.resolve();
    expect(messages.at(-1)).toEqual(expect.objectContaining({ type: "cancel-interview-assets" }));

    setInterviewAssetWarmEligibility(false);
    await Promise.resolve();
    expect(messages.at(-1)).toEqual(expect.objectContaining({ type: "cancel-interview-assets" }));

    // The explicit hook is available for a later UI action on a slow link.
    setInterviewAssetWarmEligibility(true);
    warmInterviewAssetsNow();
    await Promise.resolve();
    expect(messages.at(-1)).toEqual(expect.objectContaining({ type: "warm-interview-assets" }));
  });
});
