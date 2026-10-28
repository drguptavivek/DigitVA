const mockSecureStore = new Map<string, string>();
let mockReadError = false;
let mockWriteError = false;

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => {
    if (mockReadError) throw new Error("secure store unavailable");
    return mockSecureStore.get(key) ?? null;
  }),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (mockWriteError) throw new Error("secure store unavailable");
    mockSecureStore.set(key, value);
  }),
}));

async function freshPreferenceModule() {
  jest.resetModules();
  return require("../src/icd11DorisPreference") as typeof import("../src/icd11DorisPreference");
}

beforeEach(() => {
  mockSecureStore.clear();
  mockReadError = false;
  mockWriteError = false;
});

it("defaults missing and corrupt values to disabled and treats them as unanswered", async () => {
  let preference = await freshPreferenceModule();
  expect(await preference.isIcd11DorisEnabled()).toBe(false);
  expect(preference.useIcd11DorisPreference).toBeDefined();

  mockSecureStore.set("digitva.icd11-doris-enabled.v1", "unexpected");
  preference = await freshPreferenceModule();
  expect(await preference.isIcd11DorisEnabled()).toBe(false);
});

it("fails closed when the secure preference cannot be read", async () => {
  mockReadError = true;
  const preference = await freshPreferenceModule();
  expect(await preference.isIcd11DorisEnabled()).toBe(false);
});

it("persists a choice before publishing it and reads it after module restart", async () => {
  const preference = await freshPreferenceModule();
  expect(await preference.isIcd11DorisEnabled()).toBe(false);
  mockWriteError = true;
  await expect(preference.setIcd11DorisEnabled(true)).rejects.toThrow("secure store unavailable");
  mockWriteError = false;
  await preference.setIcd11DorisEnabled(true);
  expect(mockSecureStore.get("digitva.icd11-doris-enabled.v1")).toBe("enabled");
  expect(await preference.isIcd11DorisEnabled()).toBe(true);

  const restarted = await freshPreferenceModule();
  expect(await restarted.isIcd11DorisEnabled()).toBe(true);
});
