/**
 * Active and Demo enrolments side by side (docs/policy/public-demo.md section
 * 10.1): Active keeps today's keys, Demo prefixes them `demo.`, `active_slot`
 * missing means Active, and enrolment fills only its own slot. Each account is
 * bound to the server it signed in on, so no token, device secret or
 * credential ever goes to the other server, and writes pin their slot.
 */
const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: jest.fn(async () => undefined),
  unsentWorkCount: jest.fn(async () => 0),
}));

import { ApiError } from "../src/api";
import {
  AlreadyEnrolledError,
  authedRawRequest,
  authedRequest,
  classifyAuthError,
  createStandaloneAccount,
  enrolDemoDevice,
  enrolDevice,
  forgetDevice,
  getAuthenticatedAttachmentSource,
  loadAccounts,
  loadActiveSlot,
  loadDevice,
  NotInSlotError,
  redeemSignInQr,
  setActiveSlot,
  signIn,
  SignInRequiredError,
  signOut,
  slotKey,
  wipeInterviewer,
} from "../src/auth";
import { UNKNOWN_SERVER, accountServerChanged } from "../src/accountServer";
import { reEnrolDevice } from "../src/reEnrolConfirm";

const LIVE = "https://digitva.causeofdeathindia.com";
const DEMO = "https://digitvademo.causeofdeathindia.com";
const liveDevice = { device_id: "live-1", server: LIVE, project_id: "P", project_name: "Live" };
const demoDevice = { device_id: "demo-1", server: DEMO, project_id: "D", project_name: "Demo" };
const liveAccounts = [{ user_id: "live-user", name: "Asha", server: LIVE }];
const demoAccounts = [{ user_id: "demo-user", name: "demo.asha", server: DEMO }];

function seedBoth() {
  mockSecure.set("device", JSON.stringify(liveDevice));
  mockSecure.set("device_secret", "live-secret");
  mockSecure.set("accounts", JSON.stringify(liveAccounts));
  mockSecure.set("demo.device", JSON.stringify(demoDevice));
  mockSecure.set("demo.device_secret", "demo-secret");
  mockSecure.set("demo.accounts", JSON.stringify(demoAccounts));
}

const enrolReply = (id: string) => ({
  ok: true,
  status: 201,
  headers: { get: () => "application/json" },
  json: async () => ({ device_id: id, device_secret: `${id}-secret`, project: { project_id: "N", name: "New" } }),
  text: async () => "",
}) as unknown as Response;

let urls: string[];
beforeEach(() => {
  mockSecure.clear();
  urls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL) => {
    urls.push(String(url));
    return enrolReply("new-1");
  }) as typeof fetch;
});

it("maps a base key to today's name for Active and to demo.* for Demo", () => {
  expect(slotKey("active", "device")).toBe("device");
  expect(slotKey("active", "device_secret")).toBe("device_secret");
  expect(slotKey("active", "accounts")).toBe("accounts");
  expect(slotKey("demo", "device")).toBe("demo.device");
  expect(slotKey("demo", "device_secret")).toBe("demo.device_secret");
  expect(slotKey("demo", "accounts")).toBe("demo.accounts");
});

it("reads today's keys while active_slot is missing, and demo.* once it is demo", async () => {
  seedBoth();
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(await loadActiveSlot()).toBe("active");
  expect(await loadDevice()).toEqual(liveDevice);
  expect(await loadAccounts()).toEqual(liveAccounts);

  await setActiveSlot("demo");
  expect(mockSecure.get("active_slot")).toBe("demo");
  expect(await loadDevice()).toEqual(demoDevice);
  expect(await loadAccounts()).toEqual(demoAccounts);
  // An explicit slot reads that slot whichever is chosen.
  expect(await loadDevice("active")).toEqual(liveDevice);

  await setActiveSlot("active");
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(await loadDevice()).toEqual(liveDevice);
});

it("treats an unknown active_slot value as Active", async () => {
  seedBoth();
  mockSecure.set("active_slot", "other");
  expect(await loadActiveSlot()).toBe("active");
  expect(await loadDevice()).toEqual(liveDevice);
});

it("enrolDemoDevice fills the demo slot, chooses it, and leaves the live device and accounts alone", async () => {
  mockSecure.set("device", JSON.stringify(liveDevice));
  mockSecure.set("device_secret", "live-secret");
  mockSecure.set("accounts", JSON.stringify(liveAccounts));

  const device = await enrolDemoDevice(DEMO, "demo.asha", "correct horse battery", "Pixel", "1.0.0");

  expect(urls).toEqual([`${DEMO}/api/v1/auth/demo-enroll`]);
  expect(device).toEqual({ device_id: "new-1", server: DEMO, project_id: "N", project_name: "New" });
  expect(JSON.parse(mockSecure.get("demo.device")!)).toEqual(device);
  expect(mockSecure.get("demo.device_secret")).toBe("new-1-secret");
  expect(mockSecure.get("active_slot")).toBe("demo");
  expect(JSON.parse(mockSecure.get("device")!)).toEqual(liveDevice);
  expect(mockSecure.get("device_secret")).toBe("live-secret");
  expect(JSON.parse(mockSecure.get("accounts")!)).toEqual(liveAccounts);
});

it("enrolDevice fills today's live keys, chooses Active, and leaves the demo slot alone", async () => {
  mockSecure.set("demo.device", JSON.stringify(demoDevice));
  mockSecure.set("demo.device_secret", "demo-secret");
  mockSecure.set("demo.accounts", JSON.stringify(demoAccounts));
  mockSecure.set("active_slot", "demo");

  const device = await enrolDevice(LIVE, "CODE", "Pixel", "1.0.0");

  expect(JSON.parse(mockSecure.get("device")!)).toEqual(device);
  expect(mockSecure.get("device_secret")).toBe("new-1-secret");
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(JSON.parse(mockSecure.get("demo.device")!)).toEqual(demoDevice);
  expect(mockSecure.get("demo.device_secret")).toBe("demo-secret");
  expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual(demoAccounts);
});

it("enrolDevice on a phone without slots writes exactly today's keys", async () => {
  await enrolDevice(LIVE, "CODE", "Pixel", "1.0.0");
  expect([...mockSecure.keys()].sort()).toEqual(["device", "device_secret"]);
});

it("keeps a standalone account in Active", async () => {
  seedBoth();
  await createStandaloneAccount("local-1", "Local");
  expect(JSON.parse(mockSecure.get("accounts")!).map((a: { user_id: string }) => a.user_id))
    .toEqual(["live-user", "local-1"]);
  expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual(demoAccounts);
});

it("refuses a standalone account while Demo is chosen and writes nothing", async () => {
  seedBoth();
  await setActiveSlot("demo");
  await expect(createStandaloneAccount("local-1", "Local")).rejects.toBeInstanceOf(NotInSlotError);
  expect(JSON.parse(mockSecure.get("accounts")!).map((a: { user_id: string }) => a.user_id)).toEqual(["live-user"]);
  expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual(demoAccounts);
  expect(mockSecure.get("active_slot")).toBe("demo");
});

it("forgetting the Demo device hands the phone back to Active and leaves the live enrolment alone", async () => {
  seedBoth();
  await setActiveSlot("demo");
  await forgetDevice();
  expect(mockSecure.has("demo.device")).toBe(false);
  expect(mockSecure.has("demo.device_secret")).toBe(false);
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(JSON.parse(mockSecure.get("device")!)).toEqual(liveDevice);
  expect(mockSecure.get("device_secret")).toBe("live-secret");
  expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual(demoAccounts);
});

it("forgets a named slot's device without changing the chosen slot", async () => {
  seedBoth();
  await forgetDevice("demo");
  expect(mockSecure.has("demo.device")).toBe(false);
  expect(mockSecure.has("active_slot")).toBe(false);

  seedBoth();
  await setActiveSlot("demo");
  await forgetDevice("active");
  expect(mockSecure.has("device")).toBe(false);
  expect(mockSecure.has("device_secret")).toBe(false);
  expect(mockSecure.get("active_slot")).toBe("demo");
  expect(JSON.parse(mockSecure.get("demo.device")!)).toEqual(demoDevice);
});

it("sends a request only to the chosen slot's server, and never for a user of the other slot", async () => {
  seedBoth();
  mockSecure.set("tokens.live-user", JSON.stringify({ access_token: "live-token", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" }));
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL) => {
    urls.push(String(url));
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({}), text: async () => "{}" } as unknown as Response;
  }) as typeof fetch;

  await authedRequest("live-user", "/api/v1/me/access");
  expect(urls).toEqual([`${LIVE}/api/v1/me/access`]);

  // After a switch to Demo a queued request for the live user is refused before anything is sent.
  await setActiveSlot("demo");
  await expect(authedRequest("live-user", "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
  expect(urls).toHaveLength(1);
});

const USER_LIVE = "11111111-1111-4111-8111-111111111111";
const USER_DEMO = "22222222-2222-4222-8222-222222222222";
const access = (userId: string) => ({
  user: { user_id: userId, name: "N" }, is_admin: false, roles: [],
  demo_coding: { available: false, project_ids: [] }, projects: [],
});
const reply = (status: number, body: unknown) => ({
  ok: status < 400,
  status,
  headers: { get: () => "application/json" },
  json: async () => body,
  text: async () => JSON.stringify(body),
}) as unknown as Response;
const sessionBody = (userId: string) => ({
  access_token: `access-${userId}`, access_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  refresh_token: `refresh-${userId}`, refresh_expires_at: "",
  user: { user_id: userId, name: "N" }, access: access(userId),
});
const tokensFor = (userId: string) => JSON.stringify({
  access_token: `access-${userId}`, access_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  refresh_token: `refresh-${userId}`, refresh_expires_at: "",
});
/** Route fetches by path suffix; `before` runs first (a switch landing mid-request, say). */
function serve(routes: Record<string, () => Response>, before?: (url: string) => void) {
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL) => {
    const text = String(url);
    urls.push(text);
    before?.(text);
    const match = Object.keys(routes).find((suffix) => text.split("?")[0].endsWith(suffix));
    return match ? routes[match]() : reply(404, {});
  }) as typeof fetch;
}

describe("enrolment and sign-in fill their own slot", () => {
  it("enrolDemoDevice then signIn keeps the account, bound to the demo server, in demo.accounts only", async () => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    mockSecure.set("accounts", JSON.stringify(liveAccounts));
    serve({
      "/demo-enroll": () => enrolReply("demo-9"),
      "/sessions": () => reply(201, sessionBody(USER_DEMO)),
      "/me/access": () => reply(200, access(USER_DEMO)),
    });

    await enrolDemoDevice(DEMO, "demo.asha", "pw", "Pixel", "1.0.0");
    const account = await signIn("demo.asha", "pw");

    expect(account).toEqual({ user_id: USER_DEMO, name: "N", server: DEMO });
    expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual([expect.objectContaining({ user_id: USER_DEMO, server: DEMO })]);
    expect(mockSecure.get("accounts")).toBe(JSON.stringify(liveAccounts));
    expect(urls.every((url) => url.startsWith(DEMO))).toBe(true);
  });

  it("redeemSignInQr enrols and signs in on the Active slot, chooses it, and leaves Demo alone", async () => {
    mockSecure.set("demo.device", JSON.stringify(demoDevice));
    mockSecure.set("demo.accounts", JSON.stringify(demoAccounts));
    mockSecure.set("active_slot", "demo");
    serve({
      "/sign-in-qr/redeem": () => reply(201, { ...sessionBody(USER_LIVE), device_id: "live-9", device_secret: "s9", project: { project_id: "P", name: "Live" } }),
      "/me/access": () => reply(200, access(USER_LIVE)),
    });

    await redeemSignInQr(LIVE, "TOKEN", "Pixel", "1.0.0");

    expect(mockSecure.has("active_slot")).toBe(false);
    expect(JSON.parse(mockSecure.get("device")!).server).toBe(LIVE);
    expect(JSON.parse(mockSecure.get("accounts")!)).toEqual([expect.objectContaining({ user_id: USER_LIVE, server: LIVE })]);
    expect(JSON.parse(mockSecure.get("demo.accounts")!)).toEqual(demoAccounts);
  });

  it("a sign-in whose slot is switched mid-request keeps neither the account nor its tokens", async () => {
    mockSecure.set("demo.device", JSON.stringify(demoDevice));
    mockSecure.set("demo.device_secret", "demo-secret");
    mockSecure.set("demo.accounts", JSON.stringify(demoAccounts));
    mockSecure.set("accounts", JSON.stringify(liveAccounts));
    mockSecure.set("active_slot", "demo");
    serve({ "/sessions": () => reply(201, sessionBody(USER_DEMO)) }, () => mockSecure.delete("active_slot"));

    await expect(signIn("demo.asha", "pw")).rejects.toBeInstanceOf(NotInSlotError);

    expect(urls).toEqual([`${DEMO}/api/v1/auth/sessions`]);
    expect(mockSecure.has(`tokens.${USER_DEMO}`)).toBe(false);
    expect(mockSecure.get("demo.accounts")).toBe(JSON.stringify(demoAccounts));
    expect(mockSecure.get("accounts")).toBe(JSON.stringify(liveAccounts));
  });

  it("a sign-in pinned to a slot that is not chosen sends nothing", async () => {
    seedBoth();
    await expect(signIn("demo.asha", "pw", "demo")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([]);
  });
});

describe("an enrolment never overwrites an enrolment", () => {
  it("refuses Demo and Active enrolment over an existing device before anything is sent", async () => {
    seedBoth();
    await expect(enrolDemoDevice(DEMO, "demo.asha", "pw", "Pixel", "1.0.0")).rejects.toBeInstanceOf(AlreadyEnrolledError);
    await expect(enrolDevice(LIVE, "CODE", "Pixel", "1.0.0")).rejects.toBeInstanceOf(AlreadyEnrolledError);
    await expect(redeemSignInQr(LIVE, "TOKEN", "Pixel", "1.0.0")).rejects.toBeInstanceOf(AlreadyEnrolledError);
    expect(urls).toEqual([]);
    expect(JSON.parse(mockSecure.get("device")!)).toEqual(liveDevice);
    expect(JSON.parse(mockSecure.get("demo.device")!)).toEqual(demoDevice);
  });

  it("refuses to store an enrolment when the slot filled while the request was out", async () => {
    serve({ "/demo-enroll": () => enrolReply("demo-9") }, () => mockSecure.set("demo.device", JSON.stringify(demoDevice)));
    await expect(enrolDemoDevice(DEMO, "demo.asha", "pw", "Pixel", "1.0.0")).rejects.toBeInstanceOf(AlreadyEnrolledError);
    expect(JSON.parse(mockSecure.get("demo.device")!)).toEqual(demoDevice);
    expect(mockSecure.has("demo.device_secret")).toBe(false);
    expect(mockSecure.has("active_slot")).toBe(false);
  });

  it("re-enrolment signs out, clears the slot, and then enrols again", async () => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    serve({ "/sessions/current": () => reply(204, {}), "/enroll": () => enrolReply("live-2") });

    await reEnrolDevice(await loadAccounts(), async () => true);
    expect(mockSecure.has("device")).toBe(false);
    expect(mockSecure.has("device_secret")).toBe(false);
    // Signed out, not deleted: the profile stays and shows again on this server after sign-in.
    expect(JSON.parse(mockSecure.get("accounts")!)).toEqual([expect.objectContaining({ signed_out: true, needs_sign_in: true })]);

    await enrolDevice(LIVE, "CODE", "Pixel", "1.0.0");
    expect(JSON.parse(mockSecure.get("device")!).device_id).toBe("live-2");
    expect(urls).toEqual([`${LIVE}/api/v1/auth/sessions/current`, `${LIVE}/api/v1/auth/enroll`]);
  });
});

describe("a token goes only to the server it was issued by", () => {
  const OTHER = "https://other.example.org";
  const ATTACHMENT = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";

  it("refuses every request for an account bound to another server than the slot's device", async () => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: OTHER }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    serve({});

    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    await expect(authedRawRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    await expect(getAuthenticatedAttachmentSource(USER_LIVE, ATTACHMENT)).rejects.toBeInstanceOf(SignInRequiredError);
    expect(urls).toEqual([]);
    // Not flagged: the refusal sent nothing and is no verdict on the session.
    expect(JSON.parse(mockSecure.get("accounts")!)[0].needs_sign_in).toBeUndefined();

    // The same account on its own server is served.
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE }]));
    await expect(getAuthenticatedAttachmentSource(USER_LIVE, ATTACHMENT)).resolves.toEqual({
      uri: `${LIVE}${ATTACHMENT}`, headers: { Authorization: `Bearer access-${USER_LIVE}` },
    });
  });

  it("refresh refuses when the slot's device moved to another server since the request read it", async () => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    // A legacy account (no server): only the device check stands between the secret and the other server.
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A" }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    serve({ "/me/access": () => reply(401, { error: "unauthorized" }) }, (url) => {
      if (url.endsWith("/me/access")) mockSecure.set("device", JSON.stringify({ ...liveDevice, server: OTHER }));
    });

    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([`${LIVE}/api/v1/me/access`]);
  });

  it("refresh refuses an account bound to another server since the request read it", async () => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    serve({ "/me/access": () => reply(401, { error: "unauthorized" }) }, () => {
      mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: OTHER }]));
    });

    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([`${LIVE}/api/v1/me/access`]);
  });

  it("a revoked Active device followed by a QR enrolment elsewhere never sends the old tokens there", async () => {
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    serve({ "/enroll": () => enrolReply("other-1") });
    await enrolDevice(OTHER, "CODE", "Pixel", "1.0.0");
    urls.length = 0;

    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([]);
  });
});

describe("per-user writes land in that user's own slot", () => {
  beforeEach(() => {
    seedBoth();
    mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE }]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    mockSecure.set("active_slot", "demo");
  });
  const live = () => JSON.parse(mockSecure.get("accounts")!);

  it("flags sign-in required and the terms gate on the live account while Demo is chosen", async () => {
    await classifyAuthError(USER_LIVE, new ApiError(401, "session_expired"));
    expect(live()).toEqual([expect.objectContaining({ user_id: USER_LIVE, needs_sign_in: true })]);
    await classifyAuthError(USER_LIVE, new ApiError(403, "terms_required"));
    expect(live()).toEqual([expect.objectContaining({ user_id: USER_LIVE, terms_required: true })]);
    expect(mockSecure.get("demo.accounts")).toBe(JSON.stringify(demoAccounts));
  });

  it("blocks for maintenance on the live account while Demo is chosen", async () => {
    // The access refresh that follows is refused (not the chosen slot's user); the flag is still written.
    await classifyAuthError(USER_LIVE, new ApiError(403, "maintenance")).catch(() => undefined);
    expect(live()).toEqual([expect.objectContaining({ user_id: USER_LIVE, access_blocked: "maintenance" })]);
    expect(mockSecure.get("demo.accounts")).toBe(JSON.stringify(demoAccounts));
    expect(urls).toEqual([]);
  });

  it("writes refreshed access to the live account when Demo is chosen while the refresh is out", async () => {
    mockSecure.delete("active_slot");
    mockSecure.set(`tokens.${USER_LIVE}`, JSON.stringify({
      access_token: "old", access_expires_at: new Date(Date.now() + 1_000).toISOString(), refresh_token: "r", refresh_expires_at: "",
    }));
    serve({
      "/sessions/refresh": () => reply(200, { ...sessionBody(USER_LIVE), access: { ...access(USER_LIVE), roles: ["reviewer"] } }),
    }, () => mockSecure.set("active_slot", "demo"));

    // The switch landed, so no source is returned; the access summary still lands on the live account.
    await expect(getAuthenticatedAttachmentSource(USER_LIVE, "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg"))
      .rejects.toBeInstanceOf(SignInRequiredError);
    expect(urls).toEqual([`${LIVE}/api/v1/auth/sessions/refresh`]);
    expect(live()).toEqual([expect.objectContaining({ user_id: USER_LIVE, collection_access: false, reviewing_access: true })]);
    expect(mockSecure.get("demo.accounts")).toBe(JSON.stringify(demoAccounts));
  });

  it("wipes the live account from Active, not from the chosen Demo list", async () => {
    await wipeInterviewer(USER_LIVE);
    expect(live()).toEqual([]);
    expect(mockSecure.get("demo.accounts")).toBe(JSON.stringify(demoAccounts));
  });
});

describe("accounts kept before they recorded a server", () => {
  const OTHER = "https://other.example.org";
  const legacy = { user_id: USER_LIVE, name: "A" };
  const local = { user_id: "local-1", name: "Local", standalone: true };
  const stored = () => JSON.parse(mockSecure.get("accounts")!);
  beforeEach(() => {
    mockSecure.set("device", JSON.stringify(liveDevice));
    mockSecure.set("device_secret", "live-secret");
    mockSecure.set("accounts", JSON.stringify([legacy, local]));
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
  });

  it("are bound to the departing device's server when it is forgotten; standalone ones stay unbound", async () => {
    expect(stored()[0].server).toBeUndefined();
    await forgetDevice("active");
    expect(stored()).toEqual([{ ...legacy, server: LIVE }, local]);
  });

  it("are bound to the device's server on sign-out", async () => {
    serve({ "/sessions/current": () => reply(204, {}) });
    await signOut(USER_LIVE);
    expect(stored()).toEqual([
      expect.objectContaining({ user_id: USER_LIVE, server: LIVE, signed_out: true, needs_sign_in: true }),
      local,
    ]);
  });

  it("after re-enrolment on another server are hidden and their tokens are never sent there", async () => {
    serve({ "/sessions/current": () => reply(204, {}), "/enroll": () => enrolReply("other-1") });
    await reEnrolDevice(await loadAccounts(), async () => true);
    const device = await enrolDevice(OTHER, "CODE", "Pixel", "1.0.0");
    // Sign-out dropped the tokens; put them back so only the server binding stands in the way.
    mockSecure.set(`tokens.${USER_LIVE}`, tokensFor(USER_LIVE));
    urls.length = 0;

    const account = stored().find((item: { user_id: string }) => item.user_id === USER_LIVE);
    expect(account.server).toBe(LIVE);
    // The predicate AppState reload filters Home's list with.
    expect(accountServerChanged(account, device)).toBe(true);
    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([]);
  });

  it("after device_revoked, forgetDevice and a QR enrolment elsewhere, never send their token there", async () => {
    serve({ "/sessions": () => reply(403, { error: "Device revoked", code: "device_revoked" }), "/enroll": () => enrolReply("other-1") });
    await expect(signIn("a@example.org", "pw", "active")).rejects.toMatchObject({ code: "device_revoked" });
    // What src/nativeRoutes/sign-in.tsx does on device_revoked.
    await forgetDevice("active");
    await enrolDevice(OTHER, "CODE", "Pixel", "1.0.0");
    urls.length = 0;

    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    await expect(authedRawRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([]);
    // The account and its tokens stay on the phone, bound to the old server.
    expect(mockSecure.has(`tokens.${USER_LIVE}`)).toBe(true);
    expect(stored()[0]).toMatchObject({ user_id: USER_LIVE, server: LIVE });
  });

  it("dropped by an older app before servers were recorded are retired, not bound, by the next enrolment", async () => {
    // An older APK forgot the device on device_revoked and kept the accounts and tokens.
    mockSecure.delete("device");
    mockSecure.delete("device_secret");
    expect(mockSecure.has(`tokens.${USER_LIVE}`)).toBe(true);
    serve({ "/enroll": () => enrolReply("other-1") });
    const device = await enrolDevice(OTHER, "CODE", "Pixel", "1.0.0");
    urls.length = 0;

    const account = stored().find((item: { user_id: string }) => item.user_id === USER_LIVE);
    expect(account).toMatchObject({ server: UNKNOWN_SERVER, needs_sign_in: true });
    expect(accountServerChanged(account, device)).toBe(true);
    expect(mockSecure.has(`tokens.${USER_LIVE}`)).toBe(false);
    await expect(authedRequest(USER_LIVE, "/api/v1/me/access")).rejects.toBeInstanceOf(NotInSlotError);
    expect(urls).toEqual([]);
    // The standalone account is not anybody's server account and is left alone.
    expect(stored()).toContainEqual(local);
  });
});

it("signing in again clears signed_out and binds the account to the server it signed in on", async () => {
  mockSecure.set("device", JSON.stringify(liveDevice));
  mockSecure.set("device_secret", "live-secret");
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER_LIVE, name: "A", server: LIVE, needs_sign_in: true, signed_out: true }]));
  serve({ "/sessions": () => reply(201, sessionBody(USER_LIVE)), "/me/access": () => reply(200, access(USER_LIVE)) });

  expect(JSON.parse(mockSecure.get("accounts")!)[0].signed_out).toBe(true);
  await signIn("a@example.org", "pw");

  const [account] = JSON.parse(mockSecure.get("accounts")!);
  expect(account).toMatchObject({ user_id: USER_LIVE, server: LIVE });
  expect(account).not.toHaveProperty("signed_out");
  expect(account).not.toHaveProperty("needs_sign_in");
});
