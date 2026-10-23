const mockPrevent = jest.fn();
jest.mock("expo-screen-capture", () => ({ preventScreenCaptureAsync: mockPrevent }));

const day = (n: number) => new Date(Date.now() + n * 86400000);

function load(until?: string) {
  jest.resetModules();
  if (until === undefined) delete process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL;
  else process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL = until;
  return require("../src/screenCapture") as typeof import("../src/screenCapture");
}

beforeEach(() => mockPrevent.mockClear());
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

it("blocks a date more than 14 days away", () => {
  expect(load(day(13).toISOString()).screenshotsAllowed()).toBe(true);
  expect(load(day(15).toISOString()).screenshotsAllowed()).toBe(false);
});

it("applies the block when not allowed and skips it when allowed", () => {
  load().applyScreenCaptureBlock();
  expect(mockPrevent).toHaveBeenCalledTimes(1);
  mockPrevent.mockClear();
  load(day(3).toISOString()).applyScreenCaptureBlock();
  expect(mockPrevent).not.toHaveBeenCalled();
  load(day(-1).toISOString()).applyScreenCaptureBlock();
  expect(mockPrevent).toHaveBeenCalledTimes(1);
});
