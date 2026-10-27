/** Enrolment and sign-in-QR requests carry the Plus install UUID (S3); the plain build sends no such field. */
const mockRequestJson = jest.fn();
const mockIdentity = jest.fn();

jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 1,
  setItemAsync: jest.fn(async () => undefined),
  getItemAsync: jest.fn(async () => null),
  deleteItemAsync: jest.fn(async () => undefined),
}));
jest.mock("../src/offlineIdentity", () => ({ getOrCreatePlusDeviceIdentity: () => mockIdentity() }));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  requestJson: (...args: unknown[]) => mockRequestJson(...args),
}));

import { enrolDevice, redeemSignInQr } from "../src/auth";

const UUID = "3f8c1a52-7d0e-4b6a-9c11-2e5d8f0a7b34";
const reply = {
  device_id: "d1",
  device_secret: "s",
  project: { project_id: "UNSW01", name: "P" },
  user: { user_id: "u1", name: "Asha" },
  access_token: "a",
  refresh_token: "r",
  access: {},
};
const sentBody = () => mockRequestJson.mock.calls[0][2].body as Record<string, unknown>;

beforeEach(() => {
  jest.clearAllMocks();
  mockRequestJson.mockResolvedValue({ body: reply });
});

describe("Plus build", () => {
  beforeEach(() => mockIdentity.mockResolvedValue({ uuid: UUID, created_at: "2026-10-27T00:00:00Z" }));

  it("sends the device UUID on enrolment", async () => {
    await enrolDevice("https://s.example", "code", "Pixel", "1.0.0");
    expect(sentBody().client_device_uuid).toBe(UUID);
  });

  it("sends the device UUID on sign-in QR redeem", async () => {
    await redeemSignInQr("https://s.example", "tok", "Pixel", "1.0.0").catch(() => undefined);
    expect(sentBody().client_device_uuid).toBe(UUID);
  });
});

describe("plain build", () => {
  beforeEach(() => mockIdentity.mockResolvedValue(null));

  it("omits the field on both requests", async () => {
    await enrolDevice("https://s.example", "code", "Pixel", "1.0.0");
    expect(sentBody()).not.toHaveProperty("client_device_uuid");
    mockRequestJson.mockClear();
    await redeemSignInQr("https://s.example", "tok", "Pixel", "1.0.0").catch(() => undefined);
    expect(sentBody()).not.toHaveProperty("client_device_uuid");
  });
});
