const mockPrevent = jest.fn();
const mockAllow = jest.fn();
jest.mock("expo-screen-capture", () => ({
  allowScreenCaptureAsync: mockAllow,
  preventScreenCaptureAsync: mockPrevent,
}));

const day = (n: number) => new Date(Date.now() + n * 86400000);

function load(until?: string) {
  jest.resetModules();
  if (until === undefined) delete process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL;
  else process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL = until;
  return require("../src/screenCapture") as typeof import("../src/screenCapture");
}

beforeEach(() => {
  mockPrevent.mockClear();
  mockAllow.mockClear();
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});
afterAll(() => delete process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL);

it("allows before the date and blocks at and after it", () => {
  const until = day(7).toISOString();
  const { screenshotsAllowed } = load(until);
  expect(screenshotsAllowed(new Date())).toBe(true);
  expect(screenshotsAllowed(new Date(until))).toBe(false);
  expect(screenshotsAllowed(day(8))).toBe(false);
});

it("blocks when unset or invalid", () => {
  expect(load().screenshotsAllowed()).toBe(false);
  expect(load("").screenshotsAllowed()).toBe(false);
  expect(load("not-a-date").screenshotsAllowed()).toBe(false);
});

it("blocks a date more than four weeks away", () => {
  expect(load(day(27).toISOString()).screenshotsAllowed()).toBe(true);
  expect(load(day(29).toISOString()).screenshotsAllowed()).toBe(false);
});

it("applies the block when not allowed and skips it when allowed", () => {
  const cleanupBlocked = load().applyScreenCaptureBlock();
  expect(mockPrevent).toHaveBeenCalledTimes(1);
  mockPrevent.mockClear();
  cleanupBlocked();
  const cleanup = load(day(3).toISOString()).applyScreenCaptureBlock();
  expect(mockPrevent).not.toHaveBeenCalled();
  cleanup();
  const cleanupExpired = load(day(-1).toISOString()).applyScreenCaptureBlock();
  expect(mockPrevent).toHaveBeenCalledTimes(1);
  cleanupExpired();
});

it("blocks automatically at expiry and allows again if the clock moves back", () => {
  jest.useFakeTimers().setSystemTime(new Date("2026-11-25T08:12:09Z"));
  const { applyScreenCaptureBlock } = load("2026-11-25T08:12:10Z");
  const { AppState } = require("react-native") as typeof import("react-native");
  const remove = jest.fn();
  let onStateChange: ((state: import("react-native").AppStateStatus) => void) | undefined;
  jest.spyOn(AppState, "addEventListener").mockImplementation((_event, listener) => {
    onStateChange = listener;
    return { remove };
  });
  const cleanup = applyScreenCaptureBlock();
  expect(mockPrevent).not.toHaveBeenCalled();

  jest.advanceTimersByTime(1001);
  expect(mockPrevent).toHaveBeenCalledTimes(1);

  jest.setSystemTime(new Date("2026-11-25T08:12:09Z"));
  onStateChange?.("active");
  expect(mockAllow).toHaveBeenCalledTimes(1);
  cleanup();
  expect(remove).toHaveBeenCalledTimes(1);
});

it("rechecks the expiry when returning to the foreground after suspension", () => {
  jest.useFakeTimers().setSystemTime(new Date("2026-11-25T08:12:09Z"));
  const { applyScreenCaptureBlock } = load("2026-11-25T08:12:10Z");
  const { AppState } = require("react-native") as typeof import("react-native");
  let onStateChange: ((state: import("react-native").AppStateStatus) => void) | undefined;
  jest.spyOn(AppState, "addEventListener").mockImplementation((_event, listener) => {
    onStateChange = listener;
    return { remove: jest.fn() };
  });
  const cleanup = applyScreenCaptureBlock();

  // Simulate suspension: wall time moves beyond expiry while JS timers do not run.
  jest.setSystemTime(new Date("2026-11-25T08:12:11Z"));
  onStateChange?.("active");
  expect(mockPrevent).toHaveBeenCalledTimes(1);

  cleanup();
});
