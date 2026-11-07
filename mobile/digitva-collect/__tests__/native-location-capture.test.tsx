import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-location", () => ({ Accuracy: { High: 4, Balanced: 3 }, requestForegroundPermissionsAsync: jest.fn(), getCurrentPositionAsync: jest.fn(), getLastKnownPositionAsync: jest.fn() }));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key) }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) =>
    <button data-label={label} data-disabled={Boolean(disabled)} onClick={onPress} />,
  useUiStyles: () => ({ text: {}, muted: {}, error: {}, row: {} }),
}));

import { NativeLocationCapture, type NativeLocator } from "../src/NativeLocationCapture";

function locator(status: string, coords?: { latitude: number; longitude: number; accuracy: number | null }) {
  return {
    requestForegroundPermissionsAsync: jest.fn(async () => ({ status })),
    getCurrentPositionAsync: jest.fn(async () => ({ coords })),
    getLastKnownPositionAsync: jest.fn(async () => null),
  } as unknown as NativeLocator & { requestForegroundPermissionsAsync: jest.Mock; getCurrentPositionAsync: jest.Mock; getLastKnownPositionAsync: jest.Mock };
}
const press = async (tree: ReturnType<typeof create>, label: string) =>
  act(async () => { tree.root.findByProps({ "data-label": label }).props.onClick(); });
const text = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());

it("asks for permission only on a tap and keeps no fix when it is denied", async () => {
  const fake = locator("denied");
  const onChange = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeLocationCapture value={null} onChange={onChange} locator={fake} />); });
  expect(fake.requestForegroundPermissionsAsync).not.toHaveBeenCalled();
  await press(tree, "locationCapture");
  expect(fake.requestForegroundPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(fake.getCurrentPositionAsync).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  expect(text(tree)).toContain("locationDenied");
});

it("reads one fix with its accuracy, without any network call (offline)", async () => {
  const fetchSpy = jest.fn();
  (global as { fetch?: unknown }).fetch = fetchSpy;
  const fake = locator("granted", { latitude: 28.5, longitude: 77.2, accuracy: 12.4 });
  const onChange = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeLocationCapture value={null} onChange={onChange} locator={fake} />); });
  await press(tree, "locationCapture");
  expect(fake.getCurrentPositionAsync).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith({ latitude: 28.5, longitude: 77.2, accuracy_m: 12.4 });
  expect(fetchSpy).not.toHaveBeenCalled();
  await act(async () => { tree.update(<NativeLocationCapture value={{ latitude: 28.5, longitude: 77.2, accuracy_m: 12.4 }} onChange={onChange} locator={fake} />); });
  expect(text(tree)).toContain('locationCaptured:{\\"meters\\":12}');
  await press(tree, "locationClear");
  expect(onChange).toHaveBeenLastCalledWith(null);
});

it("shows unavailable when the device has no fix", async () => {
  const fake = locator("granted");
  fake.getCurrentPositionAsync.mockRejectedValue(new Error("no provider"));
  const onChange = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeLocationCapture value={null} onChange={onChange} locator={fake} />); });
  await press(tree, "locationCapture");
  expect(onChange).not.toHaveBeenCalled();
  expect(text(tree)).toContain("locationUnavailable");
});

async function run(fake: ReturnType<typeof locator>) {
  const onChange = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeLocationCapture value={null} onChange={onChange} locator={fake} />); });
  await press(tree, "locationCapture");
  return { onChange, tree };
}

it("falls back to a balanced fix without the settings dialog when high accuracy is refused", async () => {
  const fake = locator("granted");
  fake.getCurrentPositionAsync
    .mockRejectedValueOnce(new Error("E_LOCATION_SETTINGS_UNSATISFIED"))
    .mockResolvedValueOnce({ coords: { latitude: 1, longitude: 2, accuracy: 300 } });
  const { onChange } = await run(fake);
  expect(fake.getCurrentPositionAsync).toHaveBeenCalledTimes(2);
  expect(fake.getCurrentPositionAsync.mock.calls[1][0]).toEqual({ accuracy: 3, mayShowUserSettingsDialog: false });
  expect(onChange).toHaveBeenCalledWith({ latitude: 1, longitude: 2, accuracy_m: 300 });
});

it("uses a recent coarse last-known fix when both live reads fail, and shows unavailable only if that fails too", async () => {
  const fake = locator("granted");
  fake.getCurrentPositionAsync.mockRejectedValue(new Error("unavailable"));
  fake.getLastKnownPositionAsync.mockResolvedValueOnce({ coords: { latitude: 3, longitude: 4, accuracy: 200 } });
  const first = await run(fake);
  expect(fake.getLastKnownPositionAsync).toHaveBeenCalledWith({ maxAge: 120000, requiredAccuracy: 500 });
  expect(first.onChange).toHaveBeenCalledWith({ latitude: 3, longitude: 4, accuracy_m: 200 });
  const second = await run(fake);
  expect(second.onChange).not.toHaveBeenCalled();
  expect(text(second.tree)).toContain("locationUnavailable");
});

it("continues into the reading on the first tap after a fresh grant, retrying a not-yet-ready first read", async () => {
  const fake = locator("granted");
  fake.getCurrentPositionAsync
    .mockRejectedValueOnce(new Error("not authorized yet"))
    .mockResolvedValueOnce({ coords: { latitude: 5, longitude: 6, accuracy: 20 } });
  const { onChange } = await run(fake);
  expect(fake.requestForegroundPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith({ latitude: 5, longitude: 6, accuracy_m: 20 });
});

describe("GPS warmup", () => {
  function warmLocator(status: string) {
    const remove = jest.fn();
    let push!: (position: unknown) => void;
    const fake = Object.assign(locator("granted", { latitude: 9, longitude: 9, accuracy: 5 }), {
      getForegroundPermissionsAsync: jest.fn(async () => ({ status })),
      watchPositionAsync: jest.fn(async (_options: unknown, callback: (position: unknown) => void) => { push = callback; return { remove }; }),
    });
    return { fake: fake as unknown as NativeLocator & typeof fake, remove, push: (p: unknown) => push(p) };
  }
  const mount = async (fake: NativeLocator, watching: boolean, onChange = jest.fn()) => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<NativeLocationCapture value={null} onChange={onChange} locator={fake} watching={watching} />); });
    return { tree, onChange };
  };

  it("does not prompt or watch when permission is not already granted", async () => {
    const { fake } = warmLocator("undetermined");
    await mount(fake, true);
    expect(fake.getForegroundPermissionsAsync).toHaveBeenCalled();
    expect(fake.requestForegroundPermissionsAsync).not.toHaveBeenCalled();
    expect(fake.watchPositionAsync).not.toHaveBeenCalled();
  });

  it("watches while focused and stops on blur and unmount", async () => {
    const { fake, remove } = warmLocator("granted");
    const { tree, onChange } = await mount(fake, true);
    expect(fake.watchPositionAsync).toHaveBeenCalledTimes(1);
    await act(async () => { tree.update(<NativeLocationCapture value={null} onChange={onChange} locator={fake} watching={false} />); });
    expect(remove).toHaveBeenCalledTimes(1);
    await act(async () => { tree.update(<NativeLocationCapture value={null} onChange={onChange} locator={fake} watching />); });
    expect(fake.watchPositionAsync).toHaveBeenCalledTimes(2);
    await act(async () => tree.unmount());
    expect(remove).toHaveBeenCalledTimes(2);
  });

  it("never lets the warmup show the Android settings dialog", async () => {
    const { fake } = warmLocator("granted");
    await mount(fake, true);
    expect(fake.watchPositionAsync.mock.calls[0][0]).toMatchObject({ mayShowUserSettingsDialog: false });
  });

  it("stops warmup silently, without retry, when the watch fails", async () => {
    const { fake } = warmLocator("granted");
    fake.watchPositionAsync.mockRejectedValueOnce(new Error("settings unsatisfied"));
    const { tree } = await mount(fake, true);
    expect(fake.watchPositionAsync).toHaveBeenCalledTimes(1);
    expect(fake.requestForegroundPermissionsAsync).not.toHaveBeenCalled();
    expect(text(tree)).not.toContain("locationUnavailable");
  });

  it("stops warmup when a running watch reports an error", async () => {
    const { fake, remove } = warmLocator("granted");
    await mount(fake, true);
    await act(async () => { (fake.watchPositionAsync.mock.calls[0] as unknown[])[2] && ((fake.watchPositionAsync.mock.calls[0] as unknown[])[2] as () => void)(); });
    expect(remove).toHaveBeenCalledTimes(1);
    expect(fake.watchPositionAsync).toHaveBeenCalledTimes(1);
  });

  it("uses a fresh good warm fix on tap without a new read, and saves nothing before the tap", async () => {
    const { fake, push } = warmLocator("granted");
    const { tree, onChange } = await mount(fake, true);
    await act(async () => push({ coords: { latitude: 1, longitude: 2, accuracy: 15 } }));
    expect(onChange).not.toHaveBeenCalled();
    await press(tree, "locationCapture");
    expect(fake.getCurrentPositionAsync).not.toHaveBeenCalled();
    expect(onChange).toHaveBeenCalledWith({ latitude: 1, longitude: 2, accuracy_m: 15 });
  });

  it("reads normally when the warm fix is poor", async () => {
    const { fake, push } = warmLocator("granted");
    const { tree, onChange } = await mount(fake, true);
    await act(async () => push({ coords: { latitude: 1, longitude: 2, accuracy: 900 } }));
    await press(tree, "locationCapture");
    expect(fake.getCurrentPositionAsync).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ latitude: 9, longitude: 9, accuracy_m: 5 });
  });
});

describe("per-step timeouts", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  const hang = () => new Promise(() => {});
  const advance = (ms: number) => act(async () => { await jest.advanceTimersByTimeAsync(ms); });

  it("tries Balanced when High hangs", async () => {
    const fake = locator("granted");
    fake.getCurrentPositionAsync.mockImplementationOnce(hang).mockResolvedValueOnce({ coords: { latitude: 1, longitude: 2, accuracy: 50 } });
    const { onChange } = await run(fake);
    await advance(10000);
    expect(fake.getCurrentPositionAsync).toHaveBeenCalledTimes(2);
    expect(fake.getCurrentPositionAsync.mock.calls[1][0]).toEqual({ accuracy: 3, mayShowUserSettingsDialog: false });
    expect(onChange).toHaveBeenCalledWith({ latitude: 1, longitude: 2, accuracy_m: 50 });
  });

  it("falls back to GPS (High, no dialog) when High and Balanced fail, as after declining Location Accuracy", async () => {
    const fake = locator("granted");
    fake.getCurrentPositionAsync
      .mockRejectedValueOnce(new Error("settings unsatisfied"))
      .mockImplementationOnce(hang)
      .mockResolvedValueOnce({ coords: { latitude: 5, longitude: 6, accuracy: 8 } });
    const { onChange } = await run(fake);
    await advance(8001);
    expect(fake.getCurrentPositionAsync).toHaveBeenCalledTimes(3);
    expect(fake.getCurrentPositionAsync.mock.calls[2][0]).toEqual({ accuracy: 4, mayShowUserSettingsDialog: false });
    expect(onChange).toHaveBeenCalledWith({ latitude: 5, longitude: 6, accuracy_m: 8 });
    expect(fake.getLastKnownPositionAsync).not.toHaveBeenCalled();
  });

  it("uses last known when every live read hangs", async () => {
    const fake = locator("granted");
    fake.getCurrentPositionAsync.mockImplementation(hang);
    fake.getLastKnownPositionAsync.mockResolvedValueOnce({ coords: { latitude: 3, longitude: 4, accuracy: 200 } });
    const { onChange } = await run(fake);
    await advance(10000);
    await advance(8000);
    await advance(15000);
    expect(onChange).toHaveBeenCalledWith({ latitude: 3, longitude: 4, accuracy_m: 200 });
  });

  it("shows timeout only when every step fails by timing out", async () => {
    const fake = locator("granted");
    fake.getCurrentPositionAsync.mockImplementation(hang);
    const { onChange, tree } = await run(fake);
    await advance(10000);
    await advance(8000);
    await advance(15000);
    expect(onChange).not.toHaveBeenCalled();
    expect(text(tree)).toContain("locationTimeout");
  });

  it("drops the stale result when Retake starts a newer read", async () => {
    const fake = locator("granted", { latitude: 7, longitude: 8, accuracy: 10 });
    let resolveStale!: (v: unknown) => void;
    fake.getCurrentPositionAsync.mockImplementationOnce(() => new Promise((r) => { resolveStale = r; }));
    const { onChange, tree } = await run(fake);
    await press(tree, "locationCapturing");
    await act(async () => { resolveStale({ coords: { latitude: 1, longitude: 1, accuracy: 1 } }); });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ latitude: 7, longitude: 8, accuracy_m: 10 });
  });
});
