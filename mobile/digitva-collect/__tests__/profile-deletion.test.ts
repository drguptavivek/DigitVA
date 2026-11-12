/**
 * Profile recovery and Delete profile (docs/policy/mobile-sign-in.md section 10): the password check stores no
 * session, recovery signs the profile out keeping its store, delete refuses unsent work and an unconfirmed unknown
 * count, reports with the device credentials, and queues the report in device-level storage when offline.
 */
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
}));
const mockDeleteDb = jest.fn(async (_userId: string) => undefined);
// undefined = the store is locked; a number = it is open (a PIN unlock) with that many unsent.
const mockStoreCount = jest.fn<Promise<number | undefined>, []>(async () => 0);
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: (id: string) => mockDeleteDb(id),
  unsentWorkCount: () => mockStoreCount(),
}));
jest.mock("../src/offlineIdentity", () => ({
  getOrCreatePlusDeviceIdentity: jest.fn(async () => ({ uuid: "plus-install-uuid" })),
}));

import { clearProfileDeleteGrant, PROFILE_DELETE_WINDOW_MS } from "../src/pinResetGrant";
import {
  deleteProfile,
  hasProfileDeleteGrant,
  loadAccounts,
  ProfileDeleteRefusedError,
  recoverSignOut,
  sendQueuedProfileDeletions,
  standaloneModeAvailable,
  verifyPasswordForDelete,
  WrongAccountError,
} from "../src/auth";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const DELETIONS = `${SERVER}/api/v1/auth/profile-deletions`;

function seed(accounts: object[] = [{ user_id: USER, name: "A", server: SERVER }, { user_id: OTHER, name: "B", server: SERVER }]) {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P", project_name: "P" }));
  mockSecure.set("accounts", JSON.stringify(accounts));
  mockSecure.set(`tokens.${USER}`, JSON.stringify({ access_token: "a", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" }));
  mockSecure.set(`tokens.${OTHER}`, JSON.stringify({ access_token: "b", access_expires_at: "", refresh_token: "r2", refresh_expires_at: "" }));
}

const json = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) }) as unknown as Response;

type Call = { url: string; method?: string; auth?: string; body?: Record<string, unknown> };
let calls: Call[];
function mockServer(handler: (call: Call) => Response | Promise<Response>) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const call = { url: String(url), method: init?.method, auth: headers.Authorization, body: init?.body ? JSON.parse(init.body as string) : undefined };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}
const session = (userId: string) => json(201, { access_token: "fresh", access_expires_at: "", refresh_token: "fr", refresh_expires_at: "", user: { user_id: userId, name: "A" }, access: {} });
const queued = () => JSON.parse(mockSecure.get("profile_deletions") ?? "[]");

beforeEach(() => {
  mockSecure.clear();
  mockDeleteDb.mockClear();
  mockStoreCount.mockResolvedValue(0);
  clearProfileDeleteGrant();
});

/** A locked store with a password grant for USER (what the unlock screen has after "Use password instead"). */
async function lockedWithGrant() {
  mockStoreCount.mockResolvedValue(undefined);
  const previous = globalThis.fetch;
  mockServer((call) => (call.method === "DELETE" ? json(200, {}) : session(USER)));
  await verifyPasswordForDelete(USER, "a@example.org", "pw");
  globalThis.fetch = previous;
}

describe("password check", () => {
  it("recovery signs the profile out and keeps its store; standalone becomes available", async () => {
    seed([{ user_id: USER, name: "A", server: SERVER }]);
    mockServer((call) => (call.method === "DELETE" ? json(200, {}) : session(USER)));
    await recoverSignOut(USER, "a@example.org", "pw");
    expect(calls[0].body).toMatchObject({ device_id: "d1", device_secret: "dev-secret", email: "a@example.org", password: "pw" });
    expect(calls[1]).toMatchObject({ url: `${SERVER}/api/v1/auth/sessions/current`, method: "DELETE", auth: "Bearer fresh" });
    expect(await loadAccounts()).toEqual([expect.objectContaining({ user_id: USER, signed_out: true, needs_sign_in: true })]);
    expect(mockSecure.has(`tokens.${USER}`)).toBe(false);
    expect(mockDeleteDb).not.toHaveBeenCalled();
    expect(await standaloneModeAvailable()).toBe(true);
  });

  it("refuses another account's credentials, ends that session and changes nothing", async () => {
    seed();
    mockServer((call) => (call.method === "DELETE" ? json(200, {}) : session(OTHER)));
    await expect(recoverSignOut(USER, "b@example.org", "pw")).rejects.toBeInstanceOf(WrongAccountError);
    expect(calls.map((c) => c.method)).toEqual(["POST", "DELETE"]);
    expect((await loadAccounts()).find((a) => a.user_id === USER)?.signed_out).toBeUndefined();
    await expect(verifyPasswordForDelete(USER, "b@example.org", "pw")).rejects.toBeInstanceOf(WrongAccountError);
    expect(hasProfileDeleteGrant(USER)).toBe(false);
  });

  it("a right password grants the delete for that profile only", async () => {
    seed();
    mockServer((call) => (call.method === "DELETE" ? json(200, {}) : session(USER)));
    await verifyPasswordForDelete(USER, "a@example.org", "pw");
    expect(hasProfileDeleteGrant(USER)).toBe(true);
    expect(hasProfileDeleteGrant(OTHER)).toBe(false);
    expect(mockSecure.get(`tokens.${USER}`)).toContain("\"a\"");
  });

  it("the grant lasts two minutes and is cleared on demand (lock, cancel)", async () => {
    seed();
    mockServer((call) => (call.method === "DELETE" ? json(200, {}) : session(USER)));
    await verifyPasswordForDelete(USER, "a@example.org", "pw");
    expect(PROFILE_DELETE_WINDOW_MS).toBe(2 * 60_000);
    expect(hasProfileDeleteGrant(USER, Date.now() + PROFILE_DELETE_WINDOW_MS + 1)).toBe(false);
    await verifyPasswordForDelete(USER, "a@example.org", "pw");
    clearProfileDeleteGrant();
    expect(hasProfileDeleteGrant(USER)).toBe(false);
  });
});

describe("deleteProfile", () => {
  it("refuses without a PIN-opened store or a password grant", async () => {
    seed();
    mockStoreCount.mockResolvedValue(undefined);
    mockServer(() => json(201, { recorded: true }));
    await expect(deleteProfile(USER, null, true)).rejects.toMatchObject({ code: "not_verified" });
    await expect(deleteProfile(USER, 0, false)).rejects.toMatchObject({ code: "not_verified" });
    expect(calls).toHaveLength(0);
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("an open store's own count wins over the one passed in", async () => {
    seed();
    mockStoreCount.mockResolvedValue(2);
    mockServer(() => json(201, { recorded: true }));
    await expect(deleteProfile(USER, 0, false)).rejects.toMatchObject({ code: "unsent_work" });
    await expect(deleteProfile(USER, null, true)).rejects.toMatchObject({ code: "unsent_work" });
    expect(calls).toHaveLength(0);
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("refuses a known unsent count and an unconfirmed unknown one, sending and deleting nothing", async () => {
    seed();
    await lockedWithGrant();
    mockServer(() => json(201, { recorded: true }));
    await expect(deleteProfile(USER, 3, true)).rejects.toMatchObject({ code: "unsent_work" });
    await expect(deleteProfile(USER, null, false)).rejects.toBeInstanceOf(ProfileDeleteRefusedError);
    expect(calls).toHaveLength(0);
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("reports, then wipes this profile only, and uses the grant up", async () => {
    seed();
    await lockedWithGrant();
    mockServer(() => json(201, { recorded: true }));
    await deleteProfile(USER, null, true);
    expect(calls).toEqual([expect.objectContaining({ url: DELETIONS, auth: undefined,
      body: { device_id: "d1", device_secret: "dev-secret", user_id: USER, unsent_count: null, loss_confirmed: true } })]);
    expect(mockDeleteDb.mock.calls).toEqual([[USER]]);
    expect((await loadAccounts()).map((a) => a.user_id)).toEqual([OTHER]);
    expect(mockSecure.has(`tokens.${OTHER}`)).toBe(true);
    expect(mockSecure.has("profile_deletions")).toBe(false);
    expect(hasProfileDeleteGrant(USER)).toBe(false);
  });

  it("a 409 refusal deletes nothing", async () => {
    seed();
    mockServer(() => json(409, { code: "unsent_work" }));
    await expect(deleteProfile(USER, 0, false)).rejects.toMatchObject({ status: 409 });
    expect(mockDeleteDb).not.toHaveBeenCalled();
    expect((await loadAccounts()).map((a) => a.user_id)).toEqual([USER, OTHER]);
  });

  it("offline: deletes locally, queues the report, resends on sync until accepted", async () => {
    seed();
    mockServer(() => Promise.reject(new TypeError("Network request failed")));
    await deleteProfile(USER, 0, false);
    expect(mockDeleteDb.mock.calls).toEqual([[USER]]);
    expect(queued()).toEqual([{ slot: "active", device_id: "d1", user_id: USER, unsent_count: 0, loss_confirmed: false }]);

    mockServer(() => json(503, { code: "maintenance" }));
    await sendQueuedProfileDeletions();
    expect(queued()).toHaveLength(1);

    mockServer(() => json(201, { recorded: true }));
    await sendQueuedProfileDeletions();
    expect(calls[0].body).toMatchObject({ device_secret: "dev-secret", user_id: USER, unsent_count: 0 });
    expect(mockSecure.has("profile_deletions")).toBe(false);
  });

  it("a 404 from an older server drops the report (and deletes locally)", async () => {
    seed();
    mockServer(() => json(404, { code: "not_found" }));
    await deleteProfile(USER, 0, false);
    expect(mockDeleteDb.mock.calls).toEqual([[USER]]);
    expect(mockSecure.has("profile_deletions")).toBe(false);

    mockSecure.set("profile_deletions", JSON.stringify([{ slot: "active", device_id: "d1", user_id: USER, unsent_count: 0, loss_confirmed: false }]));
    await sendQueuedProfileDeletions();
    expect(calls.at(-1)?.url).toBe(DELETIONS);
    expect(mockSecure.has("profile_deletions")).toBe(false);
  });

  it("a standalone profile sends nothing", async () => {
    seed([{ user_id: USER, name: "A", standalone: true }]);
    mockServer(() => json(201, {}));
    await deleteProfile(USER, 0, false);
    expect(calls).toHaveLength(0);
    expect(mockDeleteDb.mock.calls).toEqual([[USER]]);
  });

  it("a report queued while a resend is in flight is kept", async () => {
    seed();
    const queuedOther = { slot: "active", device_id: "d1", user_id: OTHER, unsent_count: 0, loss_confirmed: false };
    mockSecure.set("profile_deletions", JSON.stringify([queuedOther]));
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    let first = true;
    mockServer(async (call) => {
      if (call.body?.user_id === OTHER && first) {
        first = false;
        await held;
        return json(201, { recorded: true });
      }
      throw new TypeError("Network request failed");
    });
    const resend = sendQueuedProfileDeletions();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await deleteProfile(USER, 0, false); // offline: queued while OTHER's resend waits
    release();
    await resend;
    expect(queued()).toEqual([{ slot: "active", device_id: "d1", user_id: USER, unsent_count: 0, loss_confirmed: false }]);
    expect(mockDeleteDb.mock.calls).toEqual([[USER]]);
  });
});
