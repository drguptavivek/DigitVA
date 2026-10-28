/**
 * Delete my account (docs/policy/public-privacy-and-data-requests.md section 8): a demo self-delete wipes the
 * profile on this phone only after the server deleted it; a staff request changes nothing here. Every message
 * says which of the account's audit records are kept, in English and Hindi.
 */
const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
const mockDeleteDb = jest.fn(async (_userId: string) => undefined);
jest.mock("../src/interviewerDb", () => ({
  deleteInterviewerDb: (userId: string) => mockDeleteDb(userId),
  unsentWorkCount: jest.fn(async () => 0),
}));

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";
import { ApiError } from "../src/api";
import { deleteDemoAccount, loadAccounts, loadActiveSlot, requestAccountDeletion } from "../src/auth";

const DEMO = "https://digitvademo.causeofdeathindia.com";
const USER = "demo-user";
const reply = (status: number, body: unknown) => ({
  ok: status < 400,
  status,
  headers: { get: () => "application/json" },
  json: async () => body,
  text: async () => JSON.stringify(body),
}) as unknown as Response;
const tokens = JSON.stringify({
  access_token: "access-demo", access_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  refresh_token: "refresh-demo", refresh_expires_at: "",
});

let requests: Array<{ url: string; body?: string }>;
function serve(response: Response) {
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    requests.push({ url: String(url), body: init?.body as string | undefined });
    return response;
  }) as typeof fetch;
}

beforeEach(() => {
  mockSecure.clear();
  mockDeleteDb.mockClear();
  requests = [];
  mockSecure.set("active_slot", "demo");
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO, project_id: "D", project_name: "Demo" }));
  mockSecure.set("demo.device_secret", "demo-secret");
  mockSecure.set("demo.accounts", JSON.stringify([{ user_id: USER, name: "demo.asha", server: DEMO }]));
  mockSecure.set(`tokens.${USER}`, tokens);
});

it("deletes on the server with the password, then wipes the profile, its store and tokens, and leaves Demo", async () => {
  serve(reply(200, { deleted: true }));
  await deleteDemoAccount(USER, "correct horse battery");
  expect(requests).toEqual([{ url: `${DEMO}/api/v1/me/account/delete`, body: JSON.stringify({ password: "correct horse battery" }) }]);
  expect(mockDeleteDb).toHaveBeenCalledWith(USER);
  expect(mockSecure.has(`tokens.${USER}`)).toBe(false);
  expect(await loadAccounts("demo")).toEqual([]);
  // The server deleted the device only this account used: the empty Demo slot forgets it and hands back to Active.
  expect(mockSecure.has("demo.device")).toBe(false);
  expect(await loadActiveSlot()).toBe("active");
});

it("keeps the Demo device while another demo profile remains on the phone", async () => {
  mockSecure.set("demo.accounts", JSON.stringify([
    { user_id: USER, name: "demo.asha", server: DEMO }, { user_id: "other", name: "demo.sita", server: DEMO },
  ]));
  serve(reply(200, { deleted: true }));
  await deleteDemoAccount(USER, "pw");
  expect((await loadAccounts("demo")).map((a) => a.user_id)).toEqual(["other"]);
  expect(mockSecure.has("demo.device")).toBe(true);
});

it.each([
  [400, { error: "Incorrect password.", code: "wrong_password" }],
  [409, { error: "No.", code: "deletion_refused", reason: "shared_case" }],
])("deletes nothing on this phone when the server refuses (%s)", async (status, body) => {
  serve(reply(status, body));
  await expect(deleteDemoAccount(USER, "pw")).rejects.toBeInstanceOf(ApiError);
  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect(mockSecure.get(`tokens.${USER}`)).toBe(tokens);
  expect((await loadAccounts("demo")).map((a) => a.user_id)).toEqual([USER]);
});

it("sends a staff deletion request without email or password and keeps everything here", async () => {
  serve(reply(201, { status: "pending", created: true }));
  await requestAccountDeletion(USER);
  expect(requests).toEqual([{ url: `${DEMO}/api/v1/me/deletion-request`, body: "{}" }]);
  expect(mockDeleteDb).not.toHaveBeenCalled();
  expect(mockSecure.get(`tokens.${USER}`)).toBe(tokens);
});

describe("strings", () => {
  const messages = [
    "deleteAccountDemoNote", "deleteAccountDemoConfirm", "deleteAccountDone", "deleteAccountRefusedShared",
    "deleteAccountRefusedOutside", "deleteAccountRefusedUnavailable", "deleteAccountStaffNote",
    "deleteAccountStaffConfirm", "deleteAccountRequestSent",
  ] as const;
  // A demo self-delete keeps only the security and sign-in records, without the name; the rest say audit history.
  const demoDeleted = new Set<string>(["deleteAccountDemoNote", "deleteAccountDemoConfirm", "deleteAccountDone"]);
  it.each(messages)("%s says which audit records are kept, in English and Hindi", (key) => {
    if (demoDeleted.has(key)) {
      expect(en[key]).toContain("security and sign-in audit records are kept, without its name");
      expect(hi[key]).toContain("सुरक्षा और साइन-इन ऑडिट रिकॉर्ड");
    } else {
      expect(en[key]).toContain("audit history");
      expect(hi[key]).toContain("ऑडिट इतिहास");
    }
  });
});
