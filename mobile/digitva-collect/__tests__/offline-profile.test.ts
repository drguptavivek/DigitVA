/** The offline coder profile (Collect Plus): SecureStore round-trip, validation refusals, Plus gate. */
import { Platform } from "react-native";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
}));
const mockPlus = jest.fn(() => false);
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus() }));

import * as SecureStore from "expo-secure-store";
import { getOfflineProfile, saveOfflineProfile, type OfflineProfile } from "../src/offlineProfile";

const PROFILE_KEY = "offline_profile";

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
  jest.clearAllMocks();
});

beforeEach(() => {
  mockSecure.clear();
  mockPlus.mockReturnValue(false);
  setOs("web");
});

function profileInput(overrides: Partial<OfflineProfile> = {}): OfflineProfile {
  return {
    name: "  Coder One  ",
    age_years: 41,
    sex: "female",
    designation: "health worker",
    facility_name: "PHC Rampur",
    country: " India ",
    state: "Bihar",
    hiv_mortality: "low",
    malaria_mortality: null,
    updated_at: "stale",
    ...overrides,
  };
}

it("saves a normalized profile and reads it back unchanged", async () => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  await saveOfflineProfile(profileInput());
  const stored = await getOfflineProfile();
  expect(stored).toEqual({
    name: "Coder One",
    age_years: 41,
    sex: "female",
    designation: "health worker",
    facility_name: "PHC Rampur",
    country: "India",
    state: "Bihar",
    hiv_mortality: "low",
    malaria_mortality: null,
    updated_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
  });
  expect(JSON.parse(mockSecure.get(PROFILE_KEY)!)).toEqual(stored);
});

it("refuses to save without a name", async () => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  await expect(saveOfflineProfile(profileInput({ name: "   " }))).rejects.toThrow("offline_profile_name_required");
  await expect(saveOfflineProfile(profileInput({ name: "" }))).rejects.toThrow("offline_profile_name_required");
  expect(mockSecure.size).toBe(0);
});

it("refuses to save without a country", async () => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  await expect(saveOfflineProfile(profileInput({ country: "" }))).rejects.toThrow("offline_profile_country_required");
  expect(mockSecure.size).toBe(0);
});

it("refuses an implausible age and accepts a numeric string or null", async () => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  await expect(saveOfflineProfile(profileInput({ age_years: 12.5 }))).rejects.toThrow("offline_profile_age_invalid");
  await expect(saveOfflineProfile(profileInput({ age_years: -1 }))).rejects.toThrow("offline_profile_age_invalid");
  await expect(saveOfflineProfile(profileInput({ age_years: "34" as unknown as number }))).resolves.toBeUndefined();
  expect((await getOfflineProfile())?.age_years).toBe(34);
  await expect(saveOfflineProfile(profileInput({ age_years: null }))).resolves.toBeUndefined();
  expect((await getOfflineProfile())?.age_years).toBeNull();
});

it("keeps only the allowed choice values and trims free text", async () => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  await saveOfflineProfile(profileInput({
    sex: "robot" as OfflineProfile["sex"],
    hiv_mortality: "medium" as OfflineProfile["hiv_mortality"],
    designation: "  coder  ",
  }));
  const stored = await getOfflineProfile();
  expect(stored).toMatchObject({ sex: null, hiv_mortality: null, designation: "coder" });
});

it("reads null when nothing was saved, and treats corrupt or wrong-shaped data as none", async () => {
  expect(await getOfflineProfile()).toBeNull();
  mockSecure.set(PROFILE_KEY, "{not json");
  expect(await getOfflineProfile()).toBeNull();
  mockSecure.set(PROFILE_KEY, JSON.stringify({ name: "No Country", updated_at: 3 }));
  expect(await getOfflineProfile()).toBeNull();
});

it("the plain build and the web never write a profile", async () => {
  await expect(saveOfflineProfile(profileInput())).rejects.toThrow("offline_profile_plus_only");
  setOs("android");
  await expect(saveOfflineProfile(profileInput())).rejects.toThrow("offline_profile_plus_only");
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  expect(mockSecure.size).toBe(0);
});
