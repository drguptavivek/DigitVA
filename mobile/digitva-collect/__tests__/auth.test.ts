/**
 * Refresh-token rotation: one refresh in flight per interviewer, a rotated
 * token is never spent twice, the device credentials ride on every refresh,
 * and only session_revoked wipes the store: every other refusal marks the
 * account "sign in again" and keeps its data.
 */
const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key))
}));
const mockDeleteDb = jest.fn(async (_userId: string) => undefined);
jest.mock("../src/interviewerDb", () => ({ deleteInterviewerDb: (id: string) => mockDeleteDb(id) }));

import { authedRequest, loadAccounts, SessionRevokedError, signIn, SignInRequiredError } from "../src/auth";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";

function seed(tokens: { access: string; refresh: string }) {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P", project_name: "P" }));
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER, name: "A" }, { user_id: "other", name: "B" }]));
  mockSecure.set(
    `tokens.${USER}`,
    JSON.stringify({ access_token: tokens.access, access_expires_at: "", refresh_token: tokens.refresh, refresh_expires_at: "" })
  );
}

const json = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }) as Response;

type Call = { url: string; auth?: string; body?: string };
let calls: Call[];
function mockServer(handler: (call: Call) => Response) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const call = { url: String(url), auth: headers.authorization, body: init?.body as string | undefined };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}

beforeEach(() => {
  mockSecure.clear();
  mockDeleteDb.mockClear();
});

it("rotates once for concurrent 401s and retries with the new access token", async () => {
  seed({ access: "old-access", refresh: "r1" });
  let refreshes = 0;
  mockServer((call) => {
    if (call.url.endsWith("/sessions/refresh")) {
      refreshes += 1;
      expect(JSON.parse(call.body!)).toEqual({ refresh_token: "r1", device_id: "d1", device_secret: "dev-secret" });
      return json(200, { access_token: "new-access", access_expires_at: "", refresh_token: "r2", refresh_expires_at: "" });
    }
    return call.auth === "Bearer new-access" ? json(200, { ok: true }) : json(401, { code: "token_expired" });
  });

  const results = await Promise.all([
    authedRequest(USER, "/api/v1/device/bootstrap"),
    authedRequest(USER, "/api/v1/device/bootstrap")
  ]);
  expect(results.map((r) => r.status)).toEqual([200, 200]);
  expect(refreshes).toBe(1);
  expect(JSON.parse(mockSecure.get(`tokens.${USER}`)!).refresh_token).toBe("r2");
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("wipes only this interviewer when the refresh answers session_revoked", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) =>
    call.url.endsWith("/sessions/refresh") ? json(401, { code: "session_revoked" }) : json(401, { code: "token_expired" })
  );
  await expect(authedRequest(USER, "/api/v1/device/bootstrap")).rejects.toBeInstanceOf(SessionRevokedError);
  expect(mockDeleteDb).toHaveBeenCalledWith(USER);
  expect(mockSecure.has(`tokens.${USER}`)).toBe(false);
  expect(await loadAccounts()).toEqual([{ user_id: "other", name: "B" }]);
});

describe.each([
  [401, "refresh_reused"],
  [409, "refresh_retry_race"],
  [401, "session_expired"],
  [401, "refresh_invalid"],
  [401, "device_invalid"]
])("refresh refused %i %s", (status, code) => {
  it("keeps the data and marks the account sign-in-again", async () => {
    seed({ access: "a", refresh: "r1" });
    mockServer((call) => (call.url.endsWith("/sessions/refresh") ? json(status, { code }) : json(401, {})));
    await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(SignInRequiredError);
    expect(mockDeleteDb).not.toHaveBeenCalled();
    expect(mockSecure.has(`tokens.${USER}`)).toBe(false); // dead tokens dropped
    expect(await loadAccounts()).toEqual([
      { user_id: USER, name: "A", needs_sign_in: true },
      { user_id: "other", name: "B" }
    ]);
  });
});

it("keeps everything when the network is down or the server fails", async () => {
  seed({ access: "a", refresh: "r1" });
  globalThis.fetch = jest.fn(async () => {
    throw new TypeError("Network request failed");
  }) as typeof fetch;
  await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(TypeError);

  mockServer((call) => (call.url.endsWith("/sessions/refresh") ? json(503, {}) : json(401, {})));
  await expect(authedRequest(USER, "/x")).rejects.toMatchObject({ status: 503 });

  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect(mockSecure.has(`tokens.${USER}`)).toBe(true);
  expect((await loadAccounts())[0]).toEqual({ user_id: USER, name: "A" });
});

it("clears the sign-in-again flag when the interviewer signs in again", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) => (call.url.endsWith("/sessions/refresh") ? json(401, { code: "session_expired" }) : json(401, {})));
  await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(SignInRequiredError);
  mockServer(() =>
    json(201, {
      access_token: "a2", access_expires_at: "", refresh_token: "r2", refresh_expires_at: "",
      user: { user_id: USER, name: "A" }
    })
  );
  await signIn("a@example.org", "pw");
  expect((await loadAccounts()).find((a) => a.user_id === USER)).toEqual({ user_id: USER, name: "A" });
  expect(mockDeleteDb).not.toHaveBeenCalled();
});
