/**
 * Characterization of the authenticated 401 -> refresh -> retry-once path (digitva-r8nh.20 slice 2b),
 * pinned for authedRequest (JSON, optional raw file body) and authedRawRequest (raw response) on the
 * code before they share one retry helper. Where the two differ today (the JSON-only guard against
 * retrying with a token the in-flight refresh just minted) both behaviours are pinned.
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
const mockUnsent = jest.fn(async (_userId: string): Promise<number | undefined> => 0);
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: (id: string) => mockDeleteDb(id),
  unsentWorkCount: (id: string) => mockUnsent(id),
}));
jest.mock("../src/offlineIdentity", () => ({
  getOrCreatePlusDeviceIdentity: jest.fn(async () => ({ uuid: "plus-install-uuid" })),
}));

import {
  authedRawRequest,
  authedRequest,
  loadAccounts,
  SessionRevokedError,
  SignInRequiredError,
  subscribeAccessChanges,
} from "../src/auth";
import { ApiError } from "../src/api";
import { APP_VERSION } from "../src/appVersion";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const ACCESS = { user: { user_id: USER, name: "A" }, is_admin: false, roles: [], demo_coding: { available: false, project_ids: [] }, projects: [] };
const REFRESH = `${SERVER}/api/v1/auth/sessions/refresh`;

function seed(access = "a", refresh = "r1") {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P", project_name: "P" }));
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER, name: "A" }, { user_id: "other", name: "B" }]));
  setTokens(access, refresh);
}

function setTokens(access: string, refresh: string) {
  mockSecure.set(`tokens.${USER}`, JSON.stringify({
    access_token: access, access_expires_at: "", refresh_token: refresh, refresh_expires_at: "",
  }));
}

const storedTokens = () => {
  const raw = mockSecure.get(`tokens.${USER}`);
  return raw ? JSON.parse(raw) as { access_token: string; refresh_token: string } : undefined;
};

const json = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  redirected: false,
  headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
  json: async () => body,
  text: async () => JSON.stringify(body),
}) as unknown as Response;

const rotated = (access = "b", refresh = "r2") => json(200, {
  access_token: access, access_expires_at: "", refresh_token: refresh, refresh_expires_at: "", access: ACCESS,
});

type Call = { url: string; method: string; auth?: string; body?: unknown; headers: Record<string, string> };
let calls: Call[];
function mockServer(handler: (call: Call) => Response | Promise<Response>) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const call = { url: String(url), method: init?.method ?? "GET", auth: headers.Authorization, body: init?.body, headers };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}

const refreshes = () => calls.filter((call) => call.url === REFRESH);
const trace = () => calls.map((call) => `${call.url === REFRESH ? "refresh" : call.url.replace(SERVER, "")} ${call.auth ?? ""}`.trim());

/** 401 for every token but *good*, which gets 200 {ok: true}; refresh rotates to b/r2. */
const serverAccepting = (good: string, refresh: () => Response = () => rotated()) => (call: Call) =>
  call.url === REFRESH ? refresh()
    : call.auth === `Bearer ${good}` ? json(200, { ok: true }) : json(401, { code: "token_expired" });

beforeEach(() => {
  mockSecure.clear();
  mockDeleteDb.mockClear();
  mockUnsent.mockReset();
  mockUnsent.mockResolvedValue(0);
});

type Send = (path: string) => Promise<unknown>;
const senders: [string, Send][] = [
  ["authedRequest", (path) => authedRequest(USER, path)],
  ["authedRawRequest", (path) => authedRawRequest(USER, path)],
];

describe.each(senders)("%s", (_name, send) => {
  it("401 -> one refresh with the device credentials -> retry once with the new token -> success", async () => {
    seed();
    mockServer(serverAccepting("b"));
    await expect(send("/api/v1/x")).resolves.toMatchObject({ status: 200 });
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh", "/api/v1/x Bearer b"]);
    expect(JSON.parse(refreshes()[0].body as string)).toEqual({
      refresh_token: "r1", device_id: "d1", device_secret: "dev-secret", app_version: APP_VERSION,
    });
    expect(refreshes()[0].auth).toBeUndefined();
    expect(storedTokens()).toMatchObject({ access_token: "b", refresh_token: "r2" });
  });

  it("refresh refused 401 session_expired: sign in again, data and account kept, no retry", async () => {
    seed();
    mockServer(serverAccepting("b", () => json(401, { code: "session_expired" })));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SignInRequiredError);
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh"]);
    expect(storedTokens()).toBeUndefined();
    expect((await loadAccounts()).find((a) => a.user_id === USER)).toMatchObject({ needs_sign_in: true });
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("refresh refused 409 refresh_retry_race: sign in again, data kept", async () => {
    seed();
    mockServer(serverAccepting("b", () => json(409, { code: "refresh_retry_race" })));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SignInRequiredError);
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh"]);
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("refresh refused 401 session_revoked with nothing unsent: wiped, SessionRevokedError", async () => {
    seed();
    mockServer(serverAccepting("b", () => json(401, { code: "session_revoked" })));
    const error = await send("/api/v1/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(SessionRevokedError);
    expect(mockDeleteDb).toHaveBeenCalledTimes(1);
    expect((await loadAccounts()).some((a) => a.user_id === USER)).toBe(false);
  });

  it("refresh refused 401 device_revoked: sign in again; session_revoked with unsent work: kept read-only (access_removed)", async () => {
    seed();
    mockUnsent.mockResolvedValue(3);
    mockServer(serverAccepting("b", () => json(401, { code: "device_revoked" })));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SignInRequiredError);
    mockServer(serverAccepting("c", () => json(401, { code: "session_revoked" })));
    seed();
    const error = await send("/api/v1/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(SessionRevokedError);
    expect(mockDeleteDb).not.toHaveBeenCalled();
    expect((await loadAccounts()).find((a) => a.user_id === USER)).toMatchObject({ needs_sign_in: true, access_removed: true });
  });

  it("refresh 503: the ApiError surfaces, tokens and account kept, no retry", async () => {
    seed();
    mockServer(serverAccepting("b", () => json(503, { code: "maintenance_window" })));
    await expect(send("/api/v1/x")).rejects.toMatchObject({ status: 503, code: "maintenance_window" });
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh"]);
    expect(storedTokens()).toMatchObject({ access_token: "a", refresh_token: "r1" });
    expect((await loadAccounts()).find((a) => a.user_id === USER)).not.toHaveProperty("needs_sign_in");
  });

  it("refresh network failure: the TypeError surfaces and nothing changes", async () => {
    seed();
    const failure = new TypeError("Network request failed");
    mockServer((call) => {
      if (call.url === REFRESH) throw failure;
      return json(401, { code: "token_expired" });
    });
    await expect(send("/api/v1/x")).rejects.toBe(failure);
    expect(storedTokens()).toMatchObject({ access_token: "a" });
  });

  it("401 on the retry: classified as sign in again, no second refresh, no loop", async () => {
    seed();
    mockServer(serverAccepting("never"));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SignInRequiredError);
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh", "/api/v1/x Bearer b"]);
    expect(storedTokens()).toBeUndefined();
    expect(mockDeleteDb).not.toHaveBeenCalled();
  });

  it("session_revoked on the retry wipes (nothing unsent)", async () => {
    seed();
    mockServer((call) => call.url === REFRESH ? rotated()
      : call.auth === "Bearer b" ? json(401, { code: "session_revoked" }) : json(401, { code: "token_expired" }));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SessionRevokedError);
    expect(trace()).toEqual(["/api/v1/x Bearer a", "refresh", "/api/v1/x Bearer b"]);
    expect(mockDeleteDb).toHaveBeenCalledTimes(1);
  });

  it("a non-401 refusal on the retry surfaces as the ApiError", async () => {
    seed();
    mockServer((call) => call.url === REFRESH ? rotated()
      : call.auth === "Bearer b" ? json(422, { code: "invalid" }) : json(401, { code: "token_expired" }));
    const error = await send("/api/v1/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "invalid" });
  });

  it("401 session_revoked first: no refresh, revoked at once", async () => {
    seed();
    mockServer((call) => call.url === REFRESH ? rotated() : json(401, { code: "session_revoked" }));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SessionRevokedError);
    expect(trace()).toEqual(["/api/v1/x Bearer a"]);
    expect(mockDeleteDb).toHaveBeenCalledTimes(1);
  });

  it("a non-401 refusal first: no refresh, classified (403 maintenance blocks the account)", async () => {
    seed();
    mockServer((call) => call.url.endsWith("/me/access") ? json(200, ACCESS)
      : call.url === REFRESH ? rotated() : json(403, { code: "maintenance" }));
    await expect(send("/api/v1/x")).rejects.toMatchObject({ status: 403, code: "maintenance" });
    expect(refreshes()).toHaveLength(0);
  });

  it("a network failure first: no refresh, the error surfaces", async () => {
    seed();
    const failure = new TypeError("Network request failed");
    mockServer(() => { throw failure; });
    await expect(send("/api/v1/x")).rejects.toBe(failure);
    expect(calls).toHaveLength(1);
  });

  it("tokens another call already rotated are used without a refresh", async () => {
    seed();
    mockServer((call) => {
      if (call.auth === "Bearer a") {
        setTokens("b", "r2");
        return json(401, { code: "token_expired" });
      }
      return call.auth === "Bearer b" ? json(200, { ok: true }) : rotated("z", "rz");
    });
    await expect(send("/api/v1/x")).resolves.toMatchObject({ status: 200 });
    expect(trace()).toEqual(["/api/v1/x Bearer a", "/api/v1/x Bearer b"]);
  });

  it("concurrent 401s share one refresh, and each retries once", async () => {
    seed();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    mockServer(async (call) => {
      if (call.url === REFRESH) {
        await gate;
        return rotated();
      }
      return call.auth === "Bearer b" ? json(200, { ok: true }) : json(401, { code: "token_expired" });
    });
    const pending = Promise.all([send("/api/v1/one"), send("/api/v1/two"), send("/api/v1/three")]);
    await new Promise((resolve) => setTimeout(resolve, 20));
    release();
    await expect(pending).resolves.toHaveLength(3);
    expect(refreshes()).toHaveLength(1);
    expect(calls.filter((call) => call.auth === "Bearer a")).toHaveLength(3);
    expect(calls.filter((call) => call.auth === "Bearer b").map((call) => call.url.replace(SERVER, "")).sort())
      .toEqual(["/api/v1/one", "/api/v1/three", "/api/v1/two"]);
  });

  it("no tokens: SignInRequiredError without a request", async () => {
    seed();
    mockSecure.delete(`tokens.${USER}`);
    mockServer(() => json(200, {}));
    await expect(send("/api/v1/x")).rejects.toBeInstanceOf(SignInRequiredError);
    expect(calls).toHaveLength(0);
  });
});

describe("authedRequest bodies on retry", () => {
  it("resends the same raw file bytes and SHA-256 on the retry", async () => {
    seed();
    mockServer(serverAccepting("b"));
    const bytes = new Uint8Array([7, 8, 9]);
    await authedRequest(USER, "/api/v1/intake/drafts/d/attachments/f", {
      method: "PUT", rawBody: { bytes, sha256: "e".repeat(64) },
    });
    const uploads = calls.filter((call) => call.url !== REFRESH);
    expect(uploads).toHaveLength(2);
    for (const upload of uploads) {
      expect(upload.method).toBe("PUT");
      expect(upload.body).toBe(bytes);
      expect(upload.headers["Content-Type"]).toBe("application/octet-stream");
      expect(upload.headers["X-Content-SHA256"]).toBe("e".repeat(64));
    }
  });

  it("builds a fresh body per attempt from bodyFactory, and reuses a plain body", async () => {
    seed();
    mockServer(serverAccepting("b"));
    let n = 0;
    const factory = jest.fn(() => ({ attempt: ++n }));
    await authedRequest(USER, "/api/v1/intake/submissions", { method: "POST", bodyFactory: factory, body: { ignored: true } });
    expect(factory).toHaveBeenCalledTimes(2);
    expect(calls.filter((call) => call.url !== REFRESH).map((call) => call.body))
      .toEqual([JSON.stringify({ attempt: 1 }), JSON.stringify({ attempt: 2 })]);

    seed();
    mockServer(serverAccepting("b"));
    await authedRequest(USER, "/api/v1/intake/submissions", { method: "POST", body: { same: 1 } });
    expect(calls.filter((call) => call.url !== REFRESH).map((call) => call.body))
      .toEqual([JSON.stringify({ same: 1 }), JSON.stringify({ same: 1 })]);
  });

  it("does not call bodyFactory a second time when the first attempt is not a 401", async () => {
    seed();
    mockServer(() => json(200, { ok: true }));
    const factory = jest.fn(() => ({}));
    await authedRequest(USER, "/p", { method: "POST", bodyFactory: factory });
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it("passes options through to both attempts (timeoutMs, allowList, training scope)", async () => {
    seed();
    mockServer((call) => call.url === REFRESH ? rotated()
      : call.auth === "Bearer b" ? json(200, [1]) : json(401, { code: "token_expired" }));
    await expect(authedRequest(USER, "/api/v1/codes", { allowList: true, projectId: "TRAIN" }))
      .resolves.toMatchObject({ body: [1] });
    const { rememberTrainingProject } = require("../src/auth") as typeof import("../src/auth");
    rememberTrainingProject(USER, "TRAIN");
    seed();
    mockServer((call) => call.url === REFRESH ? rotated()
      : call.auth === "Bearer b" ? json(200, {}) : json(401, { code: "token_expired" }));
    await authedRequest(USER, "/api/v1/x", { projectId: "TRAIN" });
    await authedRawRequest(USER, "/api/v1/y", { projectId: "TRAIN" });
    expect(calls.filter((call) => call.url !== REFRESH).map((call) => call.url.replace(SERVER, ""))).toEqual([
      "/api/v1/x?training=1", "/api/v1/x?training=1", "/api/v1/y?training=1",
    ]);
  });
});

describe("token minted by the refresh still in flight", () => {
  /**
   * Call C reads token b (saved by a refresh that has not finished: it is still publishing the access
   * summary) and is refused 401. authedRequest classifies that 401 at once (b is the refresh's own
   * token, so another refresh cannot help); authedRawRequest waits for the same refresh and retries once.
   */
  async function midRefresh(sendC: () => Promise<unknown>) {
    seed();
    let releaseListener!: () => void;
    let enteredListener!: () => void;
    const listenerEntered = new Promise<void>((resolve) => { enteredListener = resolve; });
    const unsubscribe = subscribeAccessChanges(() => {
      enteredListener();
      return new Promise<void>((resolve) => { releaseListener = resolve; });
    });
    mockServer((call) => call.url === REFRESH ? rotated()
      : call.url.endsWith("/first") && call.auth === "Bearer b" ? json(200, { ok: true })
        : json(401, { code: "token_expired" }));
    const first = authedRequest(USER, "/api/v1/first");
    await listenerEntered;
    expect(storedTokens()).toMatchObject({ access_token: "b" });
    const c = sendC().then((value) => ({ value }), (error: unknown) => ({ error }));
    const settledEarly = await Promise.race([c.then(() => true), new Promise((resolve) => setTimeout(() => resolve(false), 30))]);
    releaseListener();
    const [firstResult, cResult] = await Promise.all([first.then(() => "ok", (e: unknown) => e), c]);
    unsubscribe();
    return { settledEarly, firstResult, cResult };
  }

  it("authedRequest: classifies the 401 without a retry or a second refresh", async () => {
    const { settledEarly, cResult } = await midRefresh(() => authedRequest(USER, "/api/v1/c"));
    expect(settledEarly).toBe(true);
    expect((cResult as { error?: unknown }).error).toBeInstanceOf(SignInRequiredError);
    expect(calls.filter((call) => call.url.endsWith("/c")).map((call) => call.auth)).toEqual(["Bearer b"]);
    expect(refreshes()).toHaveLength(1);
  });

  it("authedRawRequest: waits for that refresh and retries once with the same token", async () => {
    const { settledEarly, cResult } = await midRefresh(() => authedRawRequest(USER, "/api/v1/c"));
    expect(settledEarly).toBe(false);
    expect((cResult as { error?: unknown }).error).toBeInstanceOf(SignInRequiredError);
    expect(calls.filter((call) => call.url.endsWith("/c")).map((call) => call.auth)).toEqual(["Bearer b", "Bearer b"]);
    expect(refreshes()).toHaveLength(1);
  });
});
