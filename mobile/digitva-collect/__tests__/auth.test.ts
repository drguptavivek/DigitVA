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
  setItemAsync: jest.fn(
    async (key: string, value: string) => void mockSecure.set(key, value),
  ),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) => `hash-${value}`),
}));
const mockDeleteDb = jest.fn(async (_userId: string) => undefined);
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: (id: string) => mockDeleteDb(id),
}));

import {
  acceptDeviceTerms,
  authedRawRequest,
  authedRequest,
  loadAccounts,
  refreshAccessSummary,
  SessionRevokedError,
  signIn,
  SignInRequiredError,
  subscribeAccessChanges,
  subscribeTermsChanges,
} from "../src/auth";
import { APP_VERSION } from "../src/appVersion";
import { recordNotificationPoll } from "../src/notificationState";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const ACCESS = { user: { user_id: USER, name: "A" }, is_admin: false, demo_coding: { available: false, project_ids: [] }, projects: [] };

function seed(tokens: { access: string; refresh: string }) {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set(
    "device",
    JSON.stringify({
      device_id: "d1",
      server: SERVER,
      project_id: "P",
      project_name: "P",
    }),
  );
  mockSecure.set(
    "accounts",
    JSON.stringify([
      { user_id: USER, name: "A" },
      { user_id: "other", name: "B" },
    ]),
  );
  mockSecure.set(
    `tokens.${USER}`,
    JSON.stringify({
      access_token: tokens.access,
      access_expires_at: "",
      refresh_token: tokens.refresh,
      refresh_expires_at: "",
    }),
  );
}

const json = (status: number, body: unknown) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

type Call = { url: string; auth?: string; body?: string };
let calls: Call[];
function mockServer(handler: (call: Call) => Response) {
  calls = [];
  globalThis.fetch = jest.fn(
    async (url: RequestInfo | URL, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const call = {
        url: String(url),
        auth: headers.Authorization ?? headers.authorization,
        body: init?.body as string | undefined,
      };
      calls.push(call);
      return handler(call);
    },
  ) as typeof fetch;
}

beforeEach(() => {
  mockSecure.clear();
  mockDeleteDb.mockClear();
});

it("preserves data and tokens through the pending terms gate and accepts through the device API", async () => {
  seed({ access: "a", refresh: "r1" });
  const changed = jest.fn();
  const unsubscribe = subscribeTermsChanges(changed);
  mockServer((call) =>
    call.url.endsWith("/terms")
      ? json(200, {})
      : json(403, { code: "terms_required" }),
  );
  await expect(
    authedRequest(USER, "/api/v1/intake/cases"),
  ).rejects.toMatchObject({ status: 403, code: "terms_required" });
  expect((await loadAccounts())[0].terms_required).toBe(true);
  expect(changed).toHaveBeenCalledTimes(1);
  await expect(
    authedRequest(USER, "/api/v1/intake/cases"),
  ).rejects.toMatchObject({ code: "terms_required" });
  expect(changed).toHaveBeenCalledTimes(1);
  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect(mockSecure.has(`tokens.${USER}`)).toBe(true);
  await acceptDeviceTerms(USER);
  expect(calls.at(-1)?.url).toBe(`${SERVER}/api/v1/me/terms`);
  expect(JSON.parse(calls.at(-1)!.body!)).toEqual({ accept_terms: true });
  expect((await loadAccounts())[0].terms_required).toBeUndefined();
  expect(changed).toHaveBeenCalledTimes(2);
  unsubscribe();
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("keeps the local store when the session has ended", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer(() => json(401, { code: "session_ended" }));
  await expect(
    authedRequest(USER, "/api/v1/intake/cases"),
  ).rejects.toBeInstanceOf(SignInRequiredError);
  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect((await loadAccounts())[0].needs_sign_in).toBe(true);
});

it("retains the terms flag returned at sign-in", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS) : json(201, {
      access_token: "a2",
      access_expires_at: "",
      refresh_token: "r2",
      refresh_expires_at: "",
      user: { user_id: USER, name: "A" },
      terms_required: true,
      access: ACCESS,
    }));
  expect((await signIn("a@example.org", "pw")).terms_required).toBe(true);
  expect(calls[0].url).toBe(`${SERVER}/api/v1/auth/sessions`);
  expect(JSON.parse(calls[0].body!)).toMatchObject({ app_version: APP_VERSION });
  expect((await loadAccounts())[1].terms_required).toBe(true);
  expect(calls.some((call) => call.url.endsWith("/me/access"))).toBe(false);
  expect(JSON.parse(mockSecure.get(`tokens.${USER}`)!)).not.toHaveProperty("access");
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("clears notification cursors when a different account signs in", async () => {
  seed({ access: "a", refresh: "r1" });
  await recordNotificationPoll(USER, 12, true);
  await recordNotificationPoll("other", 34, true);
  await recordNotificationPoll("new-user", 56, true);
  mockServer(() => json(201, {
    access_token: "new-access",
    access_expires_at: "",
    refresh_token: "new-refresh",
    refresh_expires_at: "",
    user: { user_id: "new-user", name: "New" },
    access: ACCESS,
  }));

  await signIn("new@example.org", "pw");

  expect([...mockSecure.keys()].filter((key) => key.startsWith("notification_state."))).toEqual([]);
});

it("retains refreshed tokens and the terms flag when refresh opens the terms gate", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) =>
    call.url.endsWith("/sessions/refresh")
      ? json(200, {
          access_token: "a2",
          access_expires_at: "",
          refresh_token: "r2",
          refresh_expires_at: "",
          terms_required: true,
          access: ACCESS,
        })
      : call.auth === "Bearer a2"
        ? json(403, { code: "terms_required" })
        : json(401, { code: "token_expired" }),
  );
  await expect(
    authedRequest(USER, "/api/v1/intake/cases"),
  ).rejects.toMatchObject({ code: "terms_required" });
  expect((await loadAccounts())[0].terms_required).toBe(true);
  expect(JSON.parse(mockSecure.get(`tokens.${USER}`)!).refresh_token).toBe(
    "r2",
  );
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("single-flights access refresh and publishes the authoritative summary", async () => {
  seed({ access: "a", refresh: "r1" });
  const listener = jest.fn();
  const unsubscribe = subscribeAccessChanges(listener);
  mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS) : json(200, {}));
  const [first, second] = await Promise.all([
    refreshAccessSummary(USER),
    refreshAccessSummary(USER),
  ]);
  expect(first).toEqual(ACCESS);
  expect(second).toEqual(ACCESS);
  expect(calls.filter((call) => call.url.endsWith("/me/access"))).toHaveLength(1);
  expect(listener).toHaveBeenCalledWith(USER, ACCESS);
  unsubscribe();
});

it("persists global access gates and clears them after a fresh summary", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) => call.url.endsWith("/me/access") ? json(403, { code: "maintenance" }) : json(200, {}));
  await expect(refreshAccessSummary(USER)).rejects.toMatchObject({ code: "maintenance" });
  expect((await loadAccounts())[0].access_blocked).toBe("maintenance");
  mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS) : json(200, {}));
  await refreshAccessSummary(USER);
  expect((await loadAccounts())[0].access_blocked).toBeUndefined();
});

it("rotates once for concurrent 401s and retries with the new access token", async () => {
  seed({ access: "old-access", refresh: "r1" });
  let refreshes = 0;
  mockServer((call) => {
    if (call.url.endsWith("/sessions/refresh")) {
      refreshes += 1;
      expect(JSON.parse(call.body!)).toEqual({
        refresh_token: "r1",
        device_id: "d1",
        device_secret: "dev-secret",
        app_version: APP_VERSION,
      });
      return json(200, {
        access_token: "new-access",
        access_expires_at: "",
        refresh_token: "r2",
        refresh_expires_at: "",
        access: ACCESS,
      });
    }
    return call.url.endsWith("/me/access")
      ? json(200, ACCESS)
      : call.auth === "Bearer new-access"
      ? json(200, { ok: true })
      : json(401, { code: "token_expired" });
  });

  const results = await Promise.all([
    authedRequest(USER, "/api/v1/intake/cases"),
    authedRequest(USER, "/api/v1/intake/cases"),
  ]);
  expect(results.map((r) => r.status)).toEqual([200, 200]);
  expect(refreshes).toBe(1);
  expect(JSON.parse(mockSecure.get(`tokens.${USER}`)!).refresh_token).toBe(
    "r2",
  );
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("builds a fresh request body for the authenticated retry", async () => {
  seed({ access: "old-access", refresh: "r1" });
  const bodyFactory = jest
    .fn<unknown, []>()
    .mockReturnValueOnce({ attempt: 1 })
    .mockReturnValueOnce({ attempt: 2 });
  mockServer((call) => {
    if (call.url.endsWith("/sessions/refresh"))
      return json(200, {
        access_token: "new-access",
        access_expires_at: "",
        refresh_token: "r2",
        refresh_expires_at: "",
        access: ACCESS,
      });
    return call.auth === "Bearer new-access"
      ? json(200, { ok: true })
      : json(401, { code: "token_expired" });
  });

  await expect(
    authedRequest(USER, "/api/v1/intake/submissions", {
      method: "POST",
      bodyFactory,
      timeoutMs: 120_000,
    }),
  ).resolves.toMatchObject({ status: 200 });

  const submissionCalls = calls.filter((call) =>
    call.url.endsWith("/api/v1/intake/submissions"),
  );
  expect(bodyFactory).toHaveBeenCalledTimes(2);
  expect(submissionCalls.map((call) => JSON.parse(call.body!))).toEqual([
    { attempt: 1 },
    { attempt: 2 },
  ]);
  expect(submissionCalls.map((call) => call.auth)).toEqual([
    "Bearer old-access",
    "Bearer new-access",
  ]);
});

it("does not rebuild a request body when the request fails without retry", async () => {
  seed({ access: "a", refresh: "r1" });
  const bodyFactory = jest.fn(() => ({ attempt: 1 }));
  mockServer((call) =>
    call.url.endsWith("/api/v1/intake/submissions")
      ? json(503, {})
      : json(200, {}),
  );

  await expect(
    authedRequest(USER, "/api/v1/intake/submissions", {
      method: "POST",
      bodyFactory,
    }),
  ).rejects.toMatchObject({ status: 503 });

  expect(bodyFactory).toHaveBeenCalledTimes(1);
  expect(
    calls.filter((call) => call.url.endsWith("/sessions/refresh")),
  ).toHaveLength(0);
});

it("wipes only this interviewer when the refresh answers session_revoked", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) =>
    call.url.endsWith("/sessions/refresh")
      ? json(401, { code: "session_revoked" })
      : json(401, { code: "token_expired" }),
  );
  await expect(
    authedRequest(USER, "/api/v1/intake/cases"),
  ).rejects.toBeInstanceOf(SessionRevokedError);
  expect(mockDeleteDb).toHaveBeenCalledWith(USER);
  expect(mockSecure.has(`tokens.${USER}`)).toBe(false);
  expect(await loadAccounts()).toEqual([{ user_id: "other", name: "B" }]);
});

describe.each([
  [401, "refresh_reused"],
  [409, "refresh_retry_race"],
  [401, "session_expired"],
  [401, "refresh_invalid"],
  [401, "device_invalid"],
])("refresh refused %i %s", (status, code) => {
  it("keeps the data and marks the account sign-in-again", async () => {
    seed({ access: "a", refresh: "r1" });
    mockServer((call) =>
      call.url.endsWith("/sessions/refresh")
        ? json(status, { code })
        : json(401, {}),
    );
    await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(
      SignInRequiredError,
    );
    expect(mockDeleteDb).not.toHaveBeenCalled();
    expect(mockSecure.has(`tokens.${USER}`)).toBe(false); // dead tokens dropped
    expect(await loadAccounts()).toEqual([
      { user_id: USER, name: "A", needs_sign_in: true },
      { user_id: "other", name: "B" },
    ]);
  });
});

it("keeps everything when the network is down or the server fails", async () => {
  seed({ access: "a", refresh: "r1" });
  globalThis.fetch = jest.fn(async () => {
    throw new TypeError("Network request failed");
  }) as typeof fetch;
  await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(TypeError);

  mockServer((call) =>
    call.url.endsWith("/sessions/refresh") ? json(503, {}) : json(401, {}),
  );
  await expect(authedRequest(USER, "/x")).rejects.toMatchObject({
    status: 503,
  });

  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect(mockSecure.has(`tokens.${USER}`)).toBe(true);
  expect((await loadAccounts())[0]).toEqual({ user_id: USER, name: "A" });
});

it("clears the sign-in-again flag when the interviewer signs in again", async () => {
  seed({ access: "a", refresh: "r1" });
  mockServer((call) =>
    call.url.endsWith("/sessions/refresh")
      ? json(401, { code: "session_expired" })
      : json(401, {}),
  );
  await expect(authedRequest(USER, "/x")).rejects.toBeInstanceOf(
    SignInRequiredError,
  );
  mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS) : json(201, {
      access_token: "a2",
      access_expires_at: "",
      refresh_token: "r2",
      refresh_expires_at: "",
      user: { user_id: USER, name: "A" },
      access: ACCESS,
    }));
  await signIn("a@example.org", "pw");
  expect((await loadAccounts()).find((a) => a.user_id === USER)).toEqual({
    user_id: USER,
    name: "A",
  });
  expect(mockDeleteDb).not.toHaveBeenCalled();
});

it("forwards the normalized mobile in the existing email field and ignores nullable response email", async () => {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set(
    "device",
    JSON.stringify({
      device_id: "d1",
      server: SERVER,
      project_id: "P",
      project_name: "P",
    }),
  );
  mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS) : json(201, {
      access_token: "a",
      access_expires_at: "",
      refresh_token: "r",
      refresh_expires_at: "",
      user: { user_id: USER, name: "A", email: null },
      access: ACCESS,
    }));

  const account = await signIn("+919876543210", "pw");
  expect(JSON.parse(calls[0].body!)).toMatchObject({ email: "+919876543210" });
  expect(account).toEqual({ user_id: USER, name: "A" });
  expect(await loadAccounts()).toEqual([{ user_id: USER, name: "A" }]);
});

it("shares one refresh between raw and JSON calls and retains raw response headers", async () => {
  seed({ access: "old-access", refresh: "r1" });
  let refreshes = 0;
  const rawText = '{"label":"स्वास्थ्य"}';
  mockServer((call) => {
    if (call.url.endsWith("/sessions/refresh")) {
      refreshes += 1;
      return json(200, {
        access_token: "new-access", access_expires_at: "", refresh_token: "r2",
        refresh_expires_at: "", access: ACCESS,
      });
    }
    if (call.url.endsWith("/definition")) {
      if (call.auth === "Bearer old-access") return json(401, { code: "token_expired" });
      return {
        status: 200, ok: true, redirected: false,
        headers: { get: (name: string) => ({
          "content-type": "application/json",
          etag: '"current"',
          "x-definition-sha256": "c".repeat(64),
          "content-encoding": "gzip",
        }[name.toLowerCase()] ?? null) },
        text: async () => rawText,
      } as unknown as Response;
    }
    return call.auth === "Bearer new-access"
      ? json(200, { ok: true })
      : json(401, { code: "token_expired" });
  });

  const [jsonResult, rawResult] = await Promise.all([
    authedRequest<{ ok: boolean }>(USER, "/api/v1/intake/cases"),
    authedRawRequest(USER, "/definition", { ifNoneMatch: `"${"a".repeat(64)}"`, acceptGzip: true }),
  ]);
  expect(jsonResult.body).toEqual({ ok: true });
  expect(rawResult).toMatchObject({
    status: 200,
    body: rawText,
    headers: { etag: '"current"', definitionSha256: "c".repeat(64), contentEncoding: "gzip" },
  });
  expect(refreshes).toBe(1);
  expect(calls.find((call) => call.url.endsWith("/definition") && call.auth === "Bearer new-access"))
    .toBeDefined();
  expect(mockDeleteDb).not.toHaveBeenCalled();
});
