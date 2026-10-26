/** Device identity (Collect Plus offline coding, phase 1): minted once, plus-gated, corruption regenerates. */
import { Platform } from "react-native";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({ randomUUID: () => require("node:crypto").randomUUID() }));

import * as SecureStore from "expo-secure-store";
import { getOrCreateDeviceIdentity, getOrCreatePlusDeviceIdentity } from "../src/offlineIdentity";

const getItemAsync = SecureStore.getItemAsync as jest.Mock;
const setItemAsync = SecureStore.setItemAsync as jest.Mock;

const IDENTITY_KEY = "offline_device_identity";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

beforeEach(() => {
  mockSecure.clear();
  getItemAsync.mockClear();
  setItemAsync.mockClear();
});

it("the first call mints a UUID v4, stores it as JSON and returns it", async () => {
  const identity = await getOrCreateDeviceIdentity();
  expect(identity.uuid).toMatch(UUID_V4);
  expect(new Date(identity.created_at).toISOString()).toBe(identity.created_at);
  expect(JSON.parse(mockSecure.get(IDENTITY_KEY)!)).toEqual(identity);
  expect(setItemAsync).toHaveBeenCalledTimes(1);
});

it("every later call returns the stored identity without rewriting it", async () => {
  const first = await getOrCreateDeviceIdentity();
  const second = await getOrCreateDeviceIdentity();
  expect(second).toEqual(first);
  expect(second.uuid).toBe(first.uuid);
  expect(setItemAsync).toHaveBeenCalledTimes(1);
  expect(getItemAsync).toHaveBeenCalledTimes(2);
});

it("concurrent first calls share one minted identity", async () => {
  const [a, b] = await Promise.all([getOrCreateDeviceIdentity(), getOrCreateDeviceIdentity()]);
  expect(a).toEqual(b);
  expect(setItemAsync).toHaveBeenCalledTimes(1);
});

it("a plain build returns null from the Plus gate and never touches SecureStore", async () => {
  setOs("android");
  await expect(getOrCreatePlusDeviceIdentity({}, () => false)).resolves.toBeNull();
  await expect(getOrCreatePlusDeviceIdentity({ appVariant: "development" }, () => false)).resolves.toBeNull();
  expect(getItemAsync).not.toHaveBeenCalled();
  expect(setItemAsync).not.toHaveBeenCalled();
  expect(mockSecure.size).toBe(0);
});

it("the web returns null from the Plus gate even with a plus config and engine", async () => {
  setOs("web");
  await expect(getOrCreatePlusDeviceIdentity({ appVariant: "plus" }, () => true)).resolves.toBeNull();
  expect(getItemAsync).not.toHaveBeenCalled();
  expect(mockSecure.size).toBe(0);
});

it("on Collect Plus the gate creates and then returns the same identity", async () => {
  setOs("android");
  const first = await getOrCreatePlusDeviceIdentity({ appVariant: "plus" }, () => true);
  const second = await getOrCreatePlusDeviceIdentity({ appVariant: "plus" }, () => true);
  expect(first).not.toBeNull();
  expect(second).toEqual(first);
  expect(mockSecure.get(IDENTITY_KEY)).toBe(JSON.stringify(first));
});

it("corrupted stored JSON is discarded and regenerated", async () => {
  mockSecure.set(IDENTITY_KEY, "{not json");
  const identity = await getOrCreateDeviceIdentity();
  expect(identity.uuid).toMatch(UUID_V4);
  expect(mockSecure.get(IDENTITY_KEY)).toBe(JSON.stringify(identity));
});

it("stored JSON of the wrong shape counts as corrupted and regenerates", async () => {
  mockSecure.set(IDENTITY_KEY, JSON.stringify({ uuid: "", created_at: 4 }));
  const identity = await getOrCreateDeviceIdentity();
  expect(identity.uuid).toMatch(UUID_V4);
  expect(mockSecure.get(IDENTITY_KEY)).toBe(JSON.stringify(identity));
});
