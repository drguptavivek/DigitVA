/**
 * "Try the demo": the demo origin rule, the client-side field checks, the
 * error mapping (limits are final), and the sign-up -> enrol -> sign-in calls
 * against a mocked server.
 */
import { createHash } from "node:crypto";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async () => "hash"),
}));
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: jest.fn(async () => undefined),
  unsentWorkCount: jest.fn(async () => 0),
}));

import { ApiError } from "../src/api";
import { loadAccounts, loadDevice } from "../src/auth";
import {
  DEMO_PAGES,
  demoErrorText,
  demoPageUrl,
  enrolAndSignInDemo,
  signUpDemoAccount,
  type DemoProgress,
} from "../src/demo";
import { validateSignUp } from "../src/demoRules";
import { DEMO_SERVER, demoServerOrigin, isDemoServer } from "../src/enrolment";
import { setUiLocale, t } from "../src/i18n";

describe("the demo origin rule", () => {
  it("is the compiled https demo host under the organisation's domain", () => {
    expect(DEMO_SERVER).toBe("https://digitvademo.causeofdeathindia.com");
    expect(demoServerOrigin(false)).toBe(DEMO_SERVER);
    expect(demoServerOrigin(false, undefined)).toBe(DEMO_SERVER);
  });

  it.each([
    "http://10.0.2.2:8051",
    "http://localhost:8051",
    "https://evil.example",
    "https://digitvademo.causeofdeathindia.com.evil.io",
    "http://digitvademo.causeofdeathindia.com",
  ])("a release build ignores an override such as %s", (override) => {
    expect(demoServerOrigin(false, override)).toBe(DEMO_SERVER);
  });

  it("a debug build may name a local dev server, and nothing else off the domain", () => {
    expect(demoServerOrigin(true, "http://10.0.2.2:8051")).toBe("http://10.0.2.2:8051");
    expect(demoServerOrigin(true, "http://localhost:8051/")).toBe("http://localhost:8051");
    expect(demoServerOrigin(true, "https://evil.example")).toBe(DEMO_SERVER);
    expect(demoServerOrigin(true, "http://localhost:9999")).toBe(DEMO_SERVER);
    expect(demoServerOrigin(true, "")).toBe(DEMO_SERVER);
    expect(demoServerOrigin(true, "https://other.causeofdeathindia.com")).toBe("https://other.causeofdeathindia.com");
  });

  it("recognises an enrolled demo device by its exact origin only", () => {
    expect(isDemoServer(DEMO_SERVER, false)).toBe(true);
    expect(isDemoServer("https://digitva.causeofdeathindia.com", false)).toBe(false);
    expect(isDemoServer(undefined, false)).toBe(false);
    expect(isDemoServer("http://10.0.2.2:8051", false, "http://10.0.2.2:8051")).toBe(false);
    expect(isDemoServer("http://10.0.2.2:8051", true, "http://10.0.2.2:8051")).toBe(true);
  });

  it("builds the browser links on the enrolled server", () => {
    expect(demoPageUrl(DEMO_PAGES.dashboard, DEMO_SERVER)).toBe(`${DEMO_SERVER}/public-demo/dashboard`);
    expect(demoPageUrl(DEMO_PAGES.reports, DEMO_SERVER)).toBe(`${DEMO_SERVER}/public-demo/cases`);
  });
});

describe("validateSignUp mirrors the server's rules", () => {
  const ok = "a-long-demo-password";
  it("accepts a good account", () => {
    expect(validateSignUp(" Demo.User_1 ", ok, ok)).toBeUndefined();
  });
  it.each([
    ["ab", "demoErrUsernameRule"],
    ["1abc", "demoErrUsernameRule"],
    ["9876543210", "demoErrUsernameRule"],
    ["has space", "demoErrUsernameRule"],
    ["a".repeat(31), "demoErrUsernameRule"],
    ["admin", "demoErrUsernameReserved"],
    ["a.d_min", "demoErrUsernameReserved"],
    ["support-team", "demoErrUsernameReserved"],
    ["who.me", "demoErrUsernameReserved"],
    ["demo", "demoErrUsernameReserved"],
  ])("refuses the username %j", (username, key) => {
    expect(validateSignUp(username, ok, ok)).toBe(key);
  });
  it("checks the password length, username equality and confirmation", () => {
    expect(validateSignUp("demo.user", "short", "short")).toBe("demoErrPasswordShort");
    expect(validateSignUp("long.username.here", "long.username.here", "long.username.here")).toBe("demoErrPasswordIsUsername");
    expect(validateSignUp("demo.user", ok, ok + "x")).toBe("demoErrPasswordMatch");
  });
});

describe("demoErrorText", () => {
  afterEach(() => setUiLocale("en"));
  const text = (status: number, code?: string) => demoErrorText(new ApiError(status, code));

  it("says a demo limit is final and a plain rate limit is a wait", () => {
    expect(text(429, "demo_limit")).toBe(t("demoLimit"));
    expect(text(429, "rate_limited")).toBe(t("demoRateLimited"));
    expect(text(429)).toBe(t("demoRateLimited"));
    expect(text(429, "demo_limit")).not.toBe(text(429, "rate_limited"));
  });

  it("maps the sign-up refusals", () => {
    expect(text(503, "cap_reached")).toBe("The demo is full; try again later.");
    expect(text(400, "captcha_failed")).toBe(t("demoCaptchaFailed"));
    expect(text(409, "username_taken")).toBe(t("demoErrUsernameTaken"));
    expect(text(400, "invalid_username")).toBe(t("demoErrUsernameRule"));
    expect(text(400, "breached_password")).toBe(t("demoErrBreached"));
    expect(text(503, "breach_check_unavailable")).toBe(t("demoErrBreachUnavailable"));
    expect(text(401, "invalid_credentials")).toBe(t("demoErrCredentials"));
    expect(text(404)).toBe(t("demoNotAvailable"));
    expect(text(503, "wrong_database")).toBe(t("demoNotAvailable"));
  });

  it("falls back to the shared mapping and speaks Hindi when asked", () => {
    expect(text(500, "oops")).toContain(t("errGeneric"));
    expect(demoErrorText(new TypeError("Network request failed"))).toBe(t("errNetwork"));
    setUiLocale("hi");
    expect(text(503, "cap_reached")).not.toBe("The demo is full; try again later.");
    expect(text(429, "demo_limit")).toBe(t("demoLimit"));
  });
});

const json = (status: number, body: unknown) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

type Call = { url: string; method?: string; body?: Record<string, unknown> };
let calls: Call[];
function mockServer(handler: (call: Call) => Response) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = {
      url: String(url),
      method: init?.method,
      body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
    };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}

const USER = "11111111-1111-4111-8111-111111111111";
const SALT = "a3f09c11d27e4b5586c0e1f2d3a4b5c6";
const challenge = { salt: SALT, difficulty: 10, expires: 4_000_000_000, signature: "sig" };
const ACCESS = {
  user: { user_id: USER, name: "demo.user" }, is_admin: false, roles: ["interviewer"],
  demo_coding: { available: false, project_ids: [] }, projects: [],
};

beforeEach(() => mockSecure.clear());

describe("signUpDemoAccount", () => {
  it("fetches a fresh challenge, solves it and posts the solution with the challenge fields", async () => {
    mockServer((call) => (call.url.endsWith("/challenge") ? json(200, challenge) : json(201, { user_id: USER, username: "demo.user" })));
    const stages: DemoProgress["stage"][] = [];
    await signUpDemoAccount(" Demo.User ", "a-long-demo-password", { onProgress: (p) => stages.push(p.stage) });
    expect(calls.map((c) => `${c.method ?? "GET"} ${c.url}`)).toEqual([
      `GET ${DEMO_SERVER}/api/v1/auth/demo-signup/challenge`,
      `POST ${DEMO_SERVER}/api/v1/auth/demo-signup`,
    ]);
    const posted = calls[1].body as { username: string; password: string; captcha: Record<string, unknown> };
    expect(posted.username).toBe("demo.user");
    expect(posted.captcha).toMatchObject({ salt: SALT, difficulty: 10, expires: 4_000_000_000, signature: "sig" });
    const digest = createHash("sha256").update(SALT + String(posted.captcha.solution)).digest();
    expect(digest.readUInt16BE(0) >>> 6).toBe(0); // 10 leading zero bits
    expect(stages).toEqual(expect.arrayContaining(["challenge", "solving", "signup"]));
  });

  it("gets a new challenge on every call, so a failed check is retried only by the user", async () => {
    let issued = 0;
    mockServer((call) => {
      if (call.url.endsWith("/challenge")) return json(200, { ...challenge, salt: `${SALT.slice(0, 31)}${issued++}` });
      return json(400, { code: "captcha_failed" });
    });
    await expect(signUpDemoAccount("demo.user", "a-long-demo-password")).rejects.toMatchObject({ code: "captcha_failed" });
    expect(calls).toHaveLength(2); // no automatic second try
    await expect(signUpDemoAccount("demo.user", "a-long-demo-password")).rejects.toMatchObject({ code: "captcha_failed" });
    expect(calls).toHaveLength(4);
    expect(calls[0].url).toBe(calls[2].url);
    expect((calls[1].body!.captcha as { salt: string }).salt).not.toBe((calls[3].body!.captcha as { salt: string }).salt);
  });

  it("does not post after a refused challenge request, and does not retry a rate limit", async () => {
    mockServer(() => json(429, { code: "rate_limited" }));
    await expect(signUpDemoAccount("demo.user", "a-long-demo-password")).rejects.toMatchObject({ status: 429 });
    expect(calls).toHaveLength(1);
  });

  it("refuses a malformed challenge", async () => {
    mockServer(() => json(200, { salt: 5 }));
    await expect(signUpDemoAccount("demo.user", "a-long-demo-password")).rejects.toMatchObject({ code: "malformed_response" });
    expect(calls).toHaveLength(1);
  });
});

describe("enrolAndSignInDemo", () => {
  it("enrols on the demo server, keeps it as the enrolled server and signs in with the username", async () => {
    mockServer((call) => {
      if (call.url.endsWith("/demo-enroll")) {
        return json(201, { device_id: "dev1", device_secret: "sec1", project: { project_id: "PUB01", name: "Public demo" } });
      }
      return json(201, {
        access_token: "a", access_expires_at: "x", refresh_token: "r", refresh_expires_at: "y",
        user: { user_id: USER, name: "demo.user" }, access: ACCESS,
      });
    });
    const account = await enrolAndSignInDemo(" Demo.User ", "a-long-demo-password");
    expect(account.user_id).toBe(USER);
    expect(calls.map((c) => c.url)).toEqual([
      `${DEMO_SERVER}/api/v1/auth/demo-enroll`,
      `${DEMO_SERVER}/api/v1/auth/sessions`,
    ]);
    expect(calls[0].body).toMatchObject({ username: "demo.user", password: "a-long-demo-password", platform: expect.stringMatching(/^(android|ios)$/) });
    expect(calls[1].body).toMatchObject({ device_id: "dev1", device_secret: "sec1", email: "demo.user" });
    expect(await loadDevice()).toEqual({ device_id: "dev1", server: DEMO_SERVER, project_id: "PUB01", project_name: "Public demo" });
    expect((await loadAccounts()).map((a) => a.user_id)).toEqual([USER]);
  });

  it("keeps nothing when the device cap refuses, and never retries it", async () => {
    mockServer(() => json(429, { code: "demo_limit" }));
    await expect(enrolAndSignInDemo("demo.user", "a-long-demo-password")).rejects.toMatchObject({ status: 429, code: "demo_limit" });
    expect(calls).toHaveLength(1);
    expect(await loadDevice()).toBeUndefined();
  });
});
