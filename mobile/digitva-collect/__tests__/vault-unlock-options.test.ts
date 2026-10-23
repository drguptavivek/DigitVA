/** Phone screen-lock unlock and the first-run offer counter in src/vault.ts. */
const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) => `hash-${value}`),
  getRandomBytesAsync: jest.fn(async () => new Uint8Array(32)),
}));
let mockLevel = 2;
let mockAuthSuccess = true;
const mockAuthenticate = jest.fn(async (_options: unknown) => ({ success: mockAuthSuccess }));
jest.mock("expo-local-authentication", () => ({
  SecurityLevel: { NONE: 0, SECRET: 1, BIOMETRIC_WEAK: 2, BIOMETRIC_STRONG: 3 },
  getEnrolledLevelAsync: jest.fn(async () => mockLevel),
  authenticateAsync: (options: unknown) => mockAuthenticate(options),
}));

import {
  enableScreenLock,
  forgetStoreKeys,
  noteUnlockOffer,
  readScreenLockPin,
  screenLockAvailable,
  screenLockEnabled,
  turnOffScreenLock,
  unlockOfferCount,
} from "../src/vault";

beforeEach(() => {
  mockSecure.clear();
  mockAuthenticate.mockClear();
  mockLevel = 2;
  mockAuthSuccess = true;
});

it("is available only when the phone has some screen lock", async () => {
  expect(await screenLockAvailable()).toBe(true);
  mockLevel = 0;
  expect(await screenLockAvailable()).toBe(false);
});

it("asks the phone's lock with device-credential fallback, then keeps and releases the PIN", async () => {
  await enableScreenLock("u1", "123456", "Unlock");
  expect(mockAuthenticate).toHaveBeenCalledWith(expect.objectContaining({ disableDeviceFallback: false }));
  expect(await screenLockEnabled("u1")).toBe(true);
  expect(await readScreenLockPin("u1", "Unlock")).toBe("123456");
  expect(mockAuthenticate).toHaveBeenCalledTimes(2);
});

it("stores nothing when the prompt is refused, and releases nothing when it is cancelled", async () => {
  mockAuthSuccess = false;
  await expect(enableScreenLock("u1", "123456", "Unlock")).rejects.toThrow("screen_lock_refused");
  expect(mockSecure.size).toBe(0);
  mockAuthSuccess = true;
  await enableScreenLock("u1", "123456", "Unlock");
  mockAuthSuccess = false;
  await expect(readScreenLockPin("u1", "Unlock")).rejects.toThrow("screen_lock_refused");
});

it("returns null when the option is off, and drops itself when the phone's screen lock is gone", async () => {
  expect(await readScreenLockPin("u1", "Unlock")).toBeNull();
  await enableScreenLock("u1", "123456", "Unlock");
  mockLevel = 0;
  expect(await readScreenLockPin("u1", "Unlock")).toBeNull();
  expect(await screenLockEnabled("u1")).toBe(false);
  expect([...mockSecure.keys()].some((key) => key.startsWith("pin_lock"))).toBe(false);
});

it("turn-off and the wipe remove the stored PIN; another interviewer's entry stays", async () => {
  await enableScreenLock("u1", "123456", "Unlock");
  await enableScreenLock("u2", "654321", "Unlock");
  await turnOffScreenLock("u1");
  expect(await screenLockEnabled("u1")).toBe(false);
  expect(await screenLockEnabled("u2")).toBe(true);
  await noteUnlockOffer("u2");
  await forgetStoreKeys("u2");
  expect(await screenLockEnabled("u2")).toBe(false);
  expect(await unlockOfferCount("u2")).toBe(0);
  expect(mockSecure.size).toBe(0);
});

it("counts how often the unlock offer was shown", async () => {
  expect(await unlockOfferCount("u1")).toBe(0);
  await noteUnlockOffer("u1");
  await noteUnlockOffer("u1");
  expect(await unlockOfferCount("u1")).toBe(2);
  expect(await unlockOfferCount("u2")).toBe(0);
});
